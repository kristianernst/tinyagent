"""Anthropic Messages API provider."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tinyagent.core.artifacts import tool_result_artifact_refs
from tinyagent.core.contracts import Tool
from tinyagent.core.models import ModelCapabilities, ModelSpec, ProviderError
from tinyagent.core.state import Message, ModelRequestContext, ModelResponse, ToolCall, ToolStep

DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"


@dataclass(frozen=True)
class AnthropicMessagesConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60
    context_window: int = 200_000
    max_output_tokens: int = 8_000
    anthropic_version: str = DEFAULT_ANTHROPIC_VERSION
    extra_body: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AnthropicMessagesConfig:
        values = os.environ if env is None else env
        base_url = values.get("TINYAGENT_MODEL_BASE_URL", DEFAULT_ANTHROPIC_BASE_URL)
        api_key = values.get("TINYAGENT_MODEL_API_KEY")
        model = values.get("TINYAGENT_MODEL_NAME")
        if not api_key:
            raise ProviderError("TINYAGENT_MODEL_API_KEY is required for anthropic provider.")
        if not model:
            raise ProviderError("TINYAGENT_MODEL_NAME is required for anthropic provider.")
        try:
            timeout_seconds = int(values.get("TINYAGENT_MODEL_TIMEOUT_SECONDS", "60"))
            context_window = int(values.get("TINYAGENT_MODEL_CONTEXT_WINDOW", "200000"))
            max_output_tokens = int(values.get("TINYAGENT_MODEL_MAX_OUTPUT_TOKENS", "8000"))
        except ValueError as exc:
            raise ProviderError(
                "TINYAGENT_MODEL_TIMEOUT_SECONDS, TINYAGENT_MODEL_CONTEXT_WINDOW, and TINYAGENT_MODEL_MAX_OUTPUT_TOKENS must be integers."
            ) from exc
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            anthropic_version=values.get("TINYAGENT_ANTHROPIC_VERSION", DEFAULT_ANTHROPIC_VERSION),
            extra_body=_extra_body_from_env(values),
        )


class AnthropicMessagesProvider:
    name = "anthropic"
    adapter = "tinyagent.anthropic_messages.v1"

    def __init__(self, config: AnthropicMessagesConfig) -> None:
        self.config = config
        self.model = config.model
        self.capabilities = ModelCapabilities(
            context_window=config.context_window,
            max_output_tokens=config.max_output_tokens,
            supports_tools=True,
            supports_parallel_tool_calls=True,
            supports_streaming=False,
            supports_reasoning=False,
            protocol="anthropic_messages",
            tool_result_mode="anthropic_blocks",
        )
        self.model_spec = ModelSpec(
            provider=self.name,
            model=config.model,
            protocol=self.capabilities.protocol,
            adapter=self.adapter,
            edit_style="str_replace",
            capabilities=self.capabilities,
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AnthropicMessagesProvider:
        return cls(AnthropicMessagesConfig.from_env(env))

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> ModelResponse:
        payload = self.build_payload(messages, tools, request)
        raw = self._post(payload)
        return parse_message(raw)

    def build_payload(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> dict[str, Any]:
        system, message_payloads = _messages_payload(messages)
        message_payloads.extend(_tool_history_payloads(request.tool_steps))
        payload: dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_output_tokens,
            "messages": message_payloads,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [_tool_payload(tool) for tool in tools]
        payload.update(self.config.extra_body)
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            _messages_url(self.config.base_url),
            data=body,
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": self.config.anthropic_version,
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
        except TimeoutError as exc:
            raise ProviderError(f"Model provider request timeout: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Model provider returned invalid JSON: {exc}") from exc


def parse_message(raw: Mapping[str, Any]) -> ModelResponse:
    content = raw.get("content")
    if not isinstance(content, list):
        raise ProviderError("Model provider response did not include a content list.")
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        match block.get("type"):
            case "text":
                text = block.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
            case "tool_use":
                tool_calls.append(_parse_tool_use(block))
    stop_reason = _string_or_none(raw.get("stop_reason"))
    raw_dict = dict(raw)
    usage = _usage(raw.get("usage"))
    if usage:
        raw_dict["usage"] = usage
    return ModelResponse(
        content="".join(text_parts),
        tool_calls=tuple(tool_calls),
        finish_reason="tool_calls" if tool_calls else stop_reason,
        raw=raw_dict,
    )


def _messages_payload(messages: Sequence[Message]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    payloads: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            system_parts.append(_message_text(message))
            continue
        role = "assistant" if message.role == "assistant" else "user"
        content = _message_text(message)
        if not content:
            continue
        if payloads and payloads[-1]["role"] == role:
            payloads[-1]["content"] = f"{payloads[-1]['content']}\n\n{content}"
        else:
            payloads.append({"role": role, "content": content})
    if not payloads:
        payloads.append({"role": "user", "content": ""})
    return "\n\n".join(system_parts), payloads


def _tool_history_payloads(steps: Sequence[ToolStep]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for step in steps:
        payloads.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": step.call.id,
                        "name": step.call.name,
                        "input": step.call.args,
                    }
                ],
            }
        )
        payloads.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": step.call.id,
                        "content": _tool_result_content(step),
                        "is_error": not step.result.ok,
                    }
                ],
            }
        )
    return payloads


def _tool_payload(tool: Tool) -> dict[str, Any]:
    schema = dict(tool.schema)
    parameters = schema.get("parameters")
    if not isinstance(parameters, dict):
        parameters = {"type": "object", "properties": {}}
    return {
        "name": tool.name,
        "description": str(schema.get("description") or ""),
        "input_schema": parameters,
    }


def _parse_tool_use(block: Mapping[str, Any]) -> ToolCall:
    tool_id = _string_or_none(block.get("id")) or _string_or_none(block.get("tool_use_id"))
    name = _string_or_none(block.get("name"))
    if not tool_id:
        raise ProviderError("Tool call is missing id.")
    if not name:
        raise ProviderError("Tool call is missing name.")
    raw_input = block.get("input")
    args = raw_input if isinstance(raw_input, dict) else {}
    return ToolCall(id=tool_id, name=name, args=args)


def _usage(raw_usage: object) -> dict[str, int]:
    if not isinstance(raw_usage, Mapping):
        return {}
    usage: dict[str, int] = {}
    _copy_int(raw_usage, usage, "input_tokens", "input_tokens")
    _copy_int(raw_usage, usage, "cache_read_input_tokens", "cached_input_tokens")
    _copy_int(raw_usage, usage, "cache_creation_input_tokens", "cache_creation_input_tokens")
    _copy_int(raw_usage, usage, "output_tokens", "output_tokens")
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
        usage["total_tokens"] = input_tokens + output_tokens
    return usage


def _copy_int(source: Mapping[str, Any], target: dict[str, int], source_key: str, target_key: str) -> None:
    value = source.get(source_key)
    if isinstance(value, int):
        target[target_key] = value


def _message_text(message: Message) -> str:
    if isinstance(message.content, str):
        return message.content
    return json.dumps(message.content, sort_keys=True)


def _tool_result_content(step: ToolStep) -> str:
    refs = tool_result_artifact_refs(step.result)
    if refs:
        return f"{step.result.output}\n\nArtifacts: {', '.join(refs)}"
    return step.result.output


def _messages_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/messages"


def _extra_body_from_env(values: Mapping[str, str]) -> dict[str, Any]:
    raw = values.get("TINYAGENT_MODEL_EXTRA_BODY_JSON")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"TINYAGENT_MODEL_EXTRA_BODY_JSON must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProviderError("TINYAGENT_MODEL_EXTRA_BODY_JSON must be a JSON object.")
    protected = {"messages", "model", "max_tokens", "system", "tools"}
    blocked = sorted(key for key in parsed if key in protected)
    if blocked:
        raise ProviderError(f"TINYAGENT_MODEL_EXTRA_BODY_JSON cannot override protected keys: {', '.join(blocked)}")
    return parsed


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
