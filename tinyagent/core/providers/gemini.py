"""Gemini GenerateContent provider."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from tinyagent.core.artifacts import tool_result_artifact_refs
from tinyagent.core.contracts import Tool
from tinyagent.core.events import small_event_data
from tinyagent.core.models import ModelCapabilities, ModelSpec, ProviderError
from tinyagent.core.state import Message, ModelRequestContext, ModelResponse, ToolCall, ToolStep

DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True)
class GeminiGenerateContentConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60
    context_window: int = 1_000_000
    max_output_tokens: int = 8_000
    generation_config: dict[str, Any] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GeminiGenerateContentConfig:
        values = os.environ if env is None else env
        base_url = values.get("TINYAGENT_MODEL_BASE_URL", DEFAULT_GEMINI_BASE_URL)
        api_key = values.get("TINYAGENT_MODEL_API_KEY") or values.get("GEMINI_API_KEY")
        model = values.get("TINYAGENT_MODEL_NAME")
        if not api_key:
            raise ProviderError("TINYAGENT_MODEL_API_KEY or GEMINI_API_KEY is required for gemini provider.")
        if not model:
            raise ProviderError("TINYAGENT_MODEL_NAME is required for gemini provider.")
        try:
            timeout_seconds = int(values.get("TINYAGENT_MODEL_TIMEOUT_SECONDS", "60"))
            context_window = int(values.get("TINYAGENT_MODEL_CONTEXT_WINDOW", "1000000"))
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
            generation_config=_generation_config_from_env(values),
            extra_body=_extra_body_from_env(values),
        )


class GeminiGenerateContentProvider:
    name = "gemini"
    adapter = "tinyagent.gemini_generate_content.v1"

    def __init__(self, config: GeminiGenerateContentConfig) -> None:
        self.config = config
        self.model = config.model
        self.capabilities = ModelCapabilities(
            context_window=config.context_window,
            max_output_tokens=config.max_output_tokens,
            supports_tools=True,
            supports_parallel_tool_calls=True,
            supports_streaming=False,
            supports_reasoning=False,
            protocol="gemini_generate_content",
            tool_result_mode="gemini_parts",
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
    def from_env(cls, env: Mapping[str, str] | None = None) -> GeminiGenerateContentProvider:
        return cls(GeminiGenerateContentConfig.from_env(env))

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> ModelResponse:
        payload = self.build_payload(messages, tools, request)
        raw = self._post(payload)
        return parse_generate_content(raw)

    def build_payload(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> dict[str, Any]:
        system, contents = _contents_payload(messages)
        contents.extend(_tool_history_payloads(request.tool_steps))
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                **self.config.generation_config,
                "maxOutputTokens": self.config.max_output_tokens,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": [_tool_payload(tool) for tool in tools]}]
        payload.update(self.config.extra_body)
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            _generate_content_url(self.config.base_url, self.config.model),
            data=body,
            headers={
                "x-goog-api-key": self.config.api_key,
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


def parse_generate_content(raw: Mapping[str, Any]) -> ModelResponse:
    candidates = raw.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ProviderError("Model provider response did not include candidates.")
    first = candidates[0]
    if not isinstance(first, Mapping):
        raise ProviderError("Model provider response candidate was malformed.")
    content = first.get("content")
    if not isinstance(content, Mapping):
        raise ProviderError("Model provider response did not include candidate content.")
    parts = content.get("parts")
    if not isinstance(parts, list):
        raise ProviderError("Model provider response did not include content parts.")

    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for part in parts:
        if not isinstance(part, Mapping):
            continue
        text = part.get("text")
        if isinstance(text, str):
            text_parts.append(text)
        function_call = part.get("functionCall")
        if isinstance(function_call, Mapping):
            tool_calls.append(_parse_function_call(function_call, part))

    raw_dict = dict(raw)
    usage = _usage(raw.get("usageMetadata"))
    if usage:
        raw_dict["usage"] = usage
    finish_reason = _finish_reason(first)
    return ModelResponse(
        content="".join(text_parts),
        tool_calls=tuple(tool_calls),
        finish_reason="tool_calls" if tool_calls else finish_reason,
        raw=raw_dict,
    )


def _contents_payload(messages: Sequence[Message]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in messages:
        text = _message_text(message)
        if message.role == "system":
            if text:
                system_parts.append(text)
            continue
        if not text:
            continue
        role = "model" if message.role == "assistant" else "user"
        part = {"text": text}
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].append(part)
        else:
            contents.append({"role": role, "parts": [part]})
    if not contents:
        contents.append({"role": "user", "parts": [{"text": ""}]})
    return "\n\n".join(system_parts), contents


def _tool_history_payloads(steps: Sequence[ToolStep]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for step in steps:
        function_call = {
            "id": step.call.id,
            "name": step.call.name,
            "args": step.call.args,
        }
        thought_signature = _gemini_thought_signature(step.call)
        part: dict[str, Any] = {"functionCall": function_call}
        if thought_signature:
            part["thoughtSignature"] = thought_signature
        payloads.append({"role": "model", "parts": [part]})
        payloads.append(
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "id": step.call.id,
                            "name": step.call.name,
                            "response": _tool_response_payload(step),
                        }
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
        "parameters": parameters,
    }


def _parse_function_call(function_call: Mapping[str, Any], part: Mapping[str, Any]) -> ToolCall:
    name = _string_or_none(function_call.get("name"))
    if not name:
        raise ProviderError("Tool call is missing name.")
    raw_args = function_call.get("args")
    if raw_args is None:
        raw_args = {}
    if not isinstance(raw_args, dict):
        raise ProviderError(f"Tool call arguments for {name} must be a JSON object.")
    call_id = _string_or_none(function_call.get("id"))
    metadata = _function_call_metadata(part)
    if call_id:
        return ToolCall(id=call_id, name=name, args=dict(raw_args), metadata=metadata)
    return ToolCall(name=name, args=dict(raw_args), metadata=metadata)


def _function_call_metadata(part: Mapping[str, Any]) -> dict[str, Any]:
    thought_signature = _string_or_none(part.get("thoughtSignature")) or _string_or_none(part.get("thought_signature"))
    if thought_signature:
        return {"gemini": {"thoughtSignature": thought_signature}}
    return {}


def _gemini_thought_signature(call: ToolCall) -> str | None:
    gemini = call.metadata.get("gemini")
    if isinstance(gemini, Mapping):
        return _string_or_none(gemini.get("thoughtSignature")) or _string_or_none(gemini.get("thought_signature"))
    return None


def _tool_response_payload(step: ToolStep) -> dict[str, Any]:
    result = step.result
    response: dict[str, Any] = {
        "ok": result.ok,
        "output": result.content_preview or result.output,
    }
    if result.summary:
        response["summary"] = result.summary
    if result.failure_kind or result.data.get("failure_kind"):
        response["failure_kind"] = result.failure_kind or result.data.get("failure_kind")
    if result.data:
        response["data"] = small_event_data(result.data)
    refs = tool_result_artifact_refs(result)
    if refs:
        response["artifact_refs"] = refs
    return response


def _message_text(message: Message) -> str:
    if isinstance(message.content, str):
        return message.content
    return json.dumps(message.content, sort_keys=True, ensure_ascii=False)


def _usage(raw_usage: object) -> dict[str, int]:
    if not isinstance(raw_usage, Mapping):
        return {}
    usage: dict[str, int] = {}
    _copy_int(raw_usage, usage, "promptTokenCount", "input_tokens")
    _copy_int(raw_usage, usage, "candidatesTokenCount", "output_tokens")
    _copy_int(raw_usage, usage, "thoughtsTokenCount", "reasoning_tokens")
    _copy_int(raw_usage, usage, "totalTokenCount", "total_tokens")
    return usage


def _copy_int(source: Mapping[str, Any], target: dict[str, int], source_key: str, target_key: str) -> None:
    value = source.get(source_key)
    if isinstance(value, int):
        target[target_key] = value


def _finish_reason(candidate: Mapping[str, Any]) -> str | None:
    raw = _string_or_none(candidate.get("finishReason"))
    return raw.lower() if raw else None


def _generate_content_url(base_url: str, model: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith(":generateContent"):
        return base
    model_path = model if model.startswith("models/") else f"models/{model}"
    return f"{base}/{urllib.parse.quote(model_path, safe='/')}:generateContent"


def _generation_config_from_env(values: Mapping[str, str]) -> dict[str, Any]:
    raw = values.get("TINYAGENT_GEMINI_GENERATION_CONFIG_JSON")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"TINYAGENT_GEMINI_GENERATION_CONFIG_JSON must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProviderError("TINYAGENT_GEMINI_GENERATION_CONFIG_JSON must be a JSON object.")
    protected = {"maxOutputTokens"}
    blocked = sorted(key for key in parsed if key in protected)
    if blocked:
        raise ProviderError(f"TINYAGENT_GEMINI_GENERATION_CONFIG_JSON cannot override protected keys: {', '.join(blocked)}")
    return parsed


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
    protected = {"contents", "generationConfig", "model", "systemInstruction", "toolConfig", "tools"}
    blocked = sorted(key for key in parsed if key in protected)
    if blocked:
        raise ProviderError(f"TINYAGENT_MODEL_EXTRA_BODY_JSON cannot override protected keys: {', '.join(blocked)}")
    return parsed


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
