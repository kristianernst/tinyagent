"""OpenAI-compatible Chat Completions provider."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agentd.contracts import Tool
from agentd.model_stream import ModelDelta, ProviderStreamEvent, parse_chat_completion, parse_chat_completion_chunk
from agentd.models import ProviderError
from agentd.state import Message, ModelResponse, RunState


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
        payload = self.build_payload(messages, tools, state)
        raw = self._post(payload)
        return parse_chat_completion(raw)

    def stream(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> Iterator[ModelDelta]:
        for event in self.stream_provider_events(messages, tools, state):
            yield from parse_chat_completion_chunk(event.raw)

    def stream_provider_events(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool],
        state: RunState,
    ) -> Iterator[ProviderStreamEvent]:
        payload = self.build_stream_payload(messages, tools, state)
        for raw in self._post_stream(payload):
            yield ProviderStreamEvent(provider=self.name, type=str(raw.get("object") or "chat.completion.chunk"), raw=raw)

    def build_payload(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [_message_payload(message) for message in messages],
        }
        if tools:
            payload["tools"] = [_tool_payload(tool) for tool in tools]
        return payload

    def build_stream_payload(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> dict[str, Any]:
        payload = self.build_payload(messages, tools, state)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        return payload

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

    def _post_stream(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            _chat_completions_url(self.config.base_url),
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode(errors="replace").strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        return
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(f"Model provider returned invalid stream JSON: {exc}") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise ProviderError(f"Model provider HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Model provider stream failed: {exc.reason}") from exc


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _message_payload(message: Message) -> dict[str, Any]:
    return {"role": message.role, "content": message.content}


def _tool_payload(tool: Tool) -> dict[str, Any]:
    schema = dict(tool.schema)
    if schema.get("type") == "function" and "function" in schema:
        return schema
    return {"type": "function", "function": schema}
