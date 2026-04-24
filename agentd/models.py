"""Model provider implementations."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agentd.contracts import Tool
from agentd.state import Message, ModelResponse, RunState, ToolCall


class ProviderError(RuntimeError):
    """Raised when a model provider cannot produce a response."""


class FakeModelProvider:
    """Deterministic provider for tests and offline harness runs."""

    name = "fake"

    def __init__(self, responses: Sequence[ModelResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        self.calls += 1
        if not self.responses:
            raise ProviderError("FakeModelProvider has no response left.")
        return self.responses.pop(0)


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OpenAICompatibleConfig:
        values = os.environ if env is None else env
        base_url = values.get("TINYAGENT_MODEL_BASE_URL", "https://api.openai.com/v1")
        api_key = values.get("TINYAGENT_MODEL_API_KEY")
        model = values.get("TINYAGENT_MODEL_NAME")
        if not api_key:
            raise ProviderError("TINYAGENT_MODEL_API_KEY is required for openai-compatible provider.")
        if not model:
            raise ProviderError("TINYAGENT_MODEL_NAME is required for openai-compatible provider.")
        try:
            timeout_seconds = int(values.get("TINYAGENT_MODEL_TIMEOUT_SECONDS", "60"))
        except ValueError as exc:
            raise ProviderError("TINYAGENT_MODEL_TIMEOUT_SECONDS must be an integer.") from exc
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OpenAICompatibleProvider:
        return cls(OpenAICompatibleConfig.from_env(env))

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [_message_payload(message) for message in messages],
        }
        if tools:
            payload["tools"] = [_tool_payload(tool) for tool in tools]

        raw = self._post(payload)
        return _parse_chat_completion(raw)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            _chat_completions_url(self.config.base_url),
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise ProviderError(f"Model provider HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Model provider request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Model provider returned invalid JSON: {exc}") from exc


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _message_payload(message: Message) -> dict[str, str]:
    return {"role": message.role, "content": message.content}


def _tool_payload(tool: Tool) -> dict[str, Any]:
    schema = dict(tool.schema)
    if schema.get("type") == "function" and "function" in schema:
        return schema
    return {"type": "function", "function": schema}


def _parse_chat_completion(raw: dict[str, Any]) -> ModelResponse:
    try:
        choice = raw["choices"][0]
        message = choice.get("message", {})
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("Model provider response did not include choices[0].message.") from exc

    return ModelResponse(
        content=message.get("content") or "",
        tool_calls=[_parse_tool_call(call) for call in message.get("tool_calls") or []],
        finish_reason=choice.get("finish_reason"),
        raw=raw,
    )


def _parse_tool_call(call: dict[str, Any]) -> ToolCall:
    function = call.get("function") or {}
    name = function.get("name")
    if not name:
        raise ProviderError("Tool call is missing function.name.")
    raw_arguments = function.get("arguments") or "{}"
    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"Tool call arguments for {name} are invalid JSON.") from exc
    if not isinstance(args, dict):
        raise ProviderError(f"Tool call arguments for {name} must be a JSON object.")
    return ToolCall(
        id=call.get("id") or "",
        name=name,
        args=args,
    )
