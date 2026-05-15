"""OpenAI Responses API providers."""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tinyagent.core.contracts import Tool
from tinyagent.core.model_stream import ModelDelta, ProviderStreamEvent
from tinyagent.core.models import ModelCapabilities, ModelSpec, ProviderError
from tinyagent.core.state import Message, ModelResponse, RunState, ToolCall

DEFAULT_OPENAI_RESPONSES_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CODEX_RESPONSES_BASE_URL = "https://chatgpt.com/backend-api/codex"


@dataclass(frozen=True)
class OpenAIResponsesConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60
    context_window: int = 128_000
    max_output_tokens: int = 8_000
    send_max_output_tokens: bool = True
    reasoning: dict[str, Any] | None = None
    extra_body: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OpenAIResponsesConfig:
        values = os.environ if env is None else env
        base_url = values.get("TINYAGENT_MODEL_BASE_URL", DEFAULT_OPENAI_RESPONSES_BASE_URL)
        api_key = values.get("TINYAGENT_MODEL_API_KEY")
        model = values.get("TINYAGENT_MODEL_NAME")
        if not api_key:
            raise ProviderError("TINYAGENT_MODEL_API_KEY is required for openai-responses provider.")
        if not model:
            raise ProviderError("TINYAGENT_MODEL_NAME is required for openai-responses provider.")
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            **_shared_config_from_env(values),
        )

    @classmethod
    def codex_from_env(cls, env: Mapping[str, str] | None = None) -> OpenAIResponsesConfig:
        values = os.environ if env is None else env
        base_url = (
            values.get("TINYAGENT_CODEX_BASE_URL")
            or values.get("TINYAGENT_MODEL_BASE_URL")
            or DEFAULT_CODEX_RESPONSES_BASE_URL
        )
        model = values.get("TINYAGENT_CODEX_MODEL_NAME") or values.get("TINYAGENT_MODEL_NAME")
        if not model:
            raise ProviderError("TINYAGENT_MODEL_NAME is required for openai-codex provider.")
        return cls(
            base_url=base_url,
            api_key=_codex_bearer_token(values),
            model=model,
            **_shared_config_from_env(values),
            send_max_output_tokens=False,
        )


class OpenAIResponsesProvider:
    name = "openai-responses"
    adapter = "tinyagent.openai_responses.v1"

    def __init__(
        self,
        config: OpenAIResponsesConfig,
        *,
        name: str = "openai-responses",
        adapter: str = "tinyagent.openai_responses.v1",
    ) -> None:
        self.config = config
        self.name = name
        self.adapter = adapter
        self.model = config.model
        self.capabilities = ModelCapabilities(
            context_window=config.context_window,
            max_output_tokens=config.max_output_tokens,
            supports_tools=True,
            supports_parallel_tools=False,
            supports_reasoning=True,
            tool_protocol="responses",
        )
        self.model_spec = ModelSpec(
            provider=self.name,
            model=config.model,
            protocol="responses",
            adapter=self.adapter,
            capabilities=self.capabilities,
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OpenAIResponsesProvider:
        return cls(OpenAIResponsesConfig.from_env(env))

    @classmethod
    def codex_from_env(cls, env: Mapping[str, str] | None = None) -> OpenAIResponsesProvider:
        return cls(
            OpenAIResponsesConfig.codex_from_env(env),
            name="openai-codex",
            adapter="tinyagent.openai_codex_responses.v1",
        )

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        payload = self.build_payload(messages, tools, state)
        raw = self._post(payload)
        return parse_response(raw)

    def stream(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> Iterator[ModelDelta]:
        for event in self.stream_provider_events(messages, tools, state):
            yield from parse_response_stream_event(event.raw)

    def stream_provider_events(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool],
        state: RunState,
    ) -> Iterator[ProviderStreamEvent]:
        payload = self.build_stream_payload(messages, tools, state)
        for raw in self._post_stream(payload):
            yield ProviderStreamEvent(
                provider=self.name,
                type=str(raw.get("type") or raw.get("object") or "response.event"),
                raw=raw,
            )

    def build_payload(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> dict[str, Any]:
        del state
        instructions, input_items = _responses_input(messages)
        payload: dict[str, Any] = {
            "model": self.config.model,
            "instructions": instructions,
            "input": input_items,
            "store": False,
        }
        if self.config.send_max_output_tokens:
            payload["max_output_tokens"] = self.config.max_output_tokens
        if tools:
            payload["tools"] = [_responses_tool_payload(tool) for tool in tools]
            payload["parallel_tool_calls"] = False
        if self.config.reasoning is not None:
            payload["reasoning"] = self.config.reasoning
        payload.update(self.config.extra_body)
        return payload

    def build_stream_payload(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> dict[str, Any]:
        payload = self.build_payload(messages, tools, state)
        payload["stream"] = True
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            _responses_url(self.config.base_url),
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
        except TimeoutError as exc:
            raise ProviderError(f"Model provider request timeout: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Model provider returned invalid JSON: {exc}") from exc

    def _post_stream(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            _responses_url(self.config.base_url),
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
                    if not line or line.startswith(":") or not line.startswith("data:"):
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
        except TimeoutError as exc:
            raise ProviderError(f"Model provider stream idle timeout: {exc}") from exc


def parse_response(raw: dict[str, Any]) -> ModelResponse:
    output = raw.get("output")
    if not isinstance(output, list):
        raise _provider_error("Model provider response did not include an output list.")

    content_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "message":
            content_parts.extend(_message_output_text(item))
        elif item_type == "function_call":
            tool_calls.append(_parse_response_tool_call(item))

    if not content_parts:
        output_text = raw.get("output_text")
        if isinstance(output_text, str) and output_text:
            content_parts.append(output_text)

    return ModelResponse(
        content="".join(content_parts),
        tool_calls=tuple(tool_calls),
        finish_reason="tool_calls" if tool_calls else _response_finish_reason(raw),
        raw=raw,
    )


def parse_response_stream_event(raw: dict[str, Any]) -> Iterator[ModelDelta]:
    event_type = raw.get("type")
    if not isinstance(event_type, str):
        return

    if event_type == "response.output_text.delta":
        delta = raw.get("delta")
        if isinstance(delta, str) and delta:
            yield ModelDelta(kind="text_delta", item_id=_string_or_none(raw.get("item_id")), delta=delta)
        return

    if event_type in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
        delta = raw.get("delta")
        if isinstance(delta, str) and delta:
            yield ModelDelta(
                kind="reasoning_summary_delta",
                item_id=_string_or_none(raw.get("item_id")),
                delta=delta,
                data={"provider_field": event_type},
            )
        return

    if event_type == "response.output_item.added":
        item = raw.get("item")
        if isinstance(item, dict) and item.get("type") == "function_call":
            yield _tool_call_started_delta(item, raw)
        return

    if event_type == "response.function_call_arguments.delta":
        delta = raw.get("delta")
        if isinstance(delta, str) and delta:
            yield ModelDelta(
                kind="tool_call_args_delta",
                tool_call_id=_stream_tool_id(raw),
                item_id=_string_or_none(raw.get("item_id")),
                delta=delta,
                data={"index": raw.get("output_index")},
            )
        return

    if event_type == "response.function_call_arguments.done":
        item = raw.get("item")
        data: dict[str, Any] = {"index": raw.get("output_index")}
        if isinstance(item, dict):
            data.update({"id": item.get("call_id") or item.get("id"), "name": item.get("name")})
        yield ModelDelta(
            kind="tool_call_completed",
            tool_call_id=_stream_tool_id(raw, item=item if isinstance(item, dict) else None),
            item_id=_string_or_none(raw.get("item_id")),
            data=data,
        )
        return

    if event_type == "response.completed":
        response = raw.get("response")
        if isinstance(response, dict):
            usage = response.get("usage")
            if isinstance(usage, dict):
                yield ModelDelta(kind="usage", data=usage)
            yield ModelDelta(kind="completed", data={"finish_reason": _response_finish_reason(response)})
        else:
            yield ModelDelta(kind="completed", data={"finish_reason": "stop"})
        return

    if event_type == "response.failed":
        error = raw.get("error")
        reason = error.get("message") if isinstance(error, dict) else raw.get("message")
        yield ModelDelta(kind="failed", data={"reason": reason or "response failed"})


def _responses_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/responses"):
        return base
    return f"{base}/responses"


def _responses_input(messages: Sequence[Message]) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in messages:
        content = _string_content(message.content)
        if message.role == "system":
            if content:
                instructions.append(content)
            continue
        role = message.role if message.role in {"developer", "user", "assistant"} else "user"
        input_items.append({"role": role, "content": content})
    return "\n\n".join(instructions), input_items


def _responses_tool_payload(tool: Tool) -> dict[str, Any]:
    schema = dict(tool.schema)
    if schema.get("type") == "function" and isinstance(schema.get("function"), dict):
        function = dict(schema["function"])
    else:
        function = schema
    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise ProviderError(f"Tool schema for {tool.name} is missing function name.")
    payload = {
        "type": "function",
        "name": name,
        "description": str(function.get("description") or ""),
        "parameters": function.get("parameters") if isinstance(function.get("parameters"), dict) else {"type": "object"},
        "strict": bool(function.get("strict", False)),
    }
    return payload


def _message_output_text(item: Mapping[str, Any]) -> list[str]:
    content = item.get("content")
    parts: list[str] = []
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                parts.append(part["text"])
    elif isinstance(content, str):
        parts.append(content)
    return parts


def _parse_response_tool_call(item: Mapping[str, Any]) -> ToolCall:
    name = item.get("name")
    if not isinstance(name, str) or not name:
        raise _provider_error("Tool call is missing name.")
    raw_arguments = item.get("arguments") or "{}"
    if not isinstance(raw_arguments, str):
        raw_arguments = json.dumps(raw_arguments)
    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise _provider_error(f"Tool call arguments for {name} are invalid JSON.") from exc
    if not isinstance(args, dict):
        raise _provider_error(f"Tool call arguments for {name} must be a JSON object.")
    call_id = item.get("call_id") or item.get("id")
    if isinstance(call_id, str) and call_id:
        return ToolCall(id=call_id, name=name, args=args)
    return ToolCall(name=name, args=args)


def _tool_call_started_delta(item: Mapping[str, Any], raw: Mapping[str, Any]) -> ModelDelta:
    call_id = item.get("call_id") or item.get("id") or raw.get("item_id")
    return ModelDelta(
        kind="tool_call_started",
        tool_call_id=str(call_id) if call_id else _stream_tool_id(raw, item=item),
        item_id=_string_or_none(raw.get("item_id") or item.get("id")),
        data={
            "index": raw.get("output_index"),
            "id": call_id,
            "name": item.get("name"),
            "type": "function",
        },
    )


def _stream_tool_id(raw: Mapping[str, Any], *, item: Mapping[str, Any] | None = None) -> str:
    if item is not None:
        call_id = item.get("call_id") or item.get("id")
        if isinstance(call_id, str) and call_id:
            return call_id
    item_id = raw.get("item_id")
    if isinstance(item_id, str) and item_id:
        return item_id
    index = raw.get("output_index")
    return f"index_{index}" if index is not None else "index_0"


def _response_finish_reason(raw: Mapping[str, Any]) -> str | None:
    output = raw.get("output")
    if isinstance(output, list) and any(isinstance(item, dict) and item.get("type") == "function_call" for item in output):
        return "tool_calls"
    status = raw.get("status")
    if status == "completed":
        return "stop"
    if status == "incomplete":
        details = raw.get("incomplete_details")
        if isinstance(details, dict):
            reason = details.get("reason")
            if isinstance(reason, str):
                return reason
        return "incomplete"
    return str(status) if status is not None else None


def _shared_config_from_env(values: Mapping[str, str]) -> dict[str, Any]:
    try:
        timeout_seconds = int(values.get("TINYAGENT_MODEL_TIMEOUT_SECONDS", "60"))
    except ValueError as exc:
        raise ProviderError("TINYAGENT_MODEL_TIMEOUT_SECONDS must be an integer.") from exc
    try:
        context_window = int(values.get("TINYAGENT_MODEL_CONTEXT_WINDOW", "128000"))
        max_output_tokens = int(values.get("TINYAGENT_MODEL_MAX_OUTPUT_TOKENS", "8000"))
    except ValueError as exc:
        raise ProviderError("TINYAGENT_MODEL_CONTEXT_WINDOW and TINYAGENT_MODEL_MAX_OUTPUT_TOKENS must be integers.") from exc
    return {
        "timeout_seconds": timeout_seconds,
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "reasoning": _reasoning_from_env(values),
        "extra_body": _extra_body_from_env(values),
    }


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
    protected = {"input", "instructions", "messages", "model", "stream", "store", "tools"}
    blocked = sorted(key for key in parsed if key in protected)
    if blocked:
        raise ProviderError(f"TINYAGENT_MODEL_EXTRA_BODY_JSON cannot override protected keys: {', '.join(blocked)}")
    return parsed


def _reasoning_from_env(values: Mapping[str, str]) -> dict[str, Any] | None:
    raw = values.get("TINYAGENT_MODEL_REASONING_JSON")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"TINYAGENT_MODEL_REASONING_JSON must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ProviderError("TINYAGENT_MODEL_REASONING_JSON must be a JSON object.")
    return parsed


def _codex_bearer_token(values: Mapping[str, str]) -> str:
    direct = values.get("TINYAGENT_CODEX_BEARER_TOKEN")
    if direct and direct.strip():
        return direct.strip()
    command = values.get("TINYAGENT_CODEX_AUTH_COMMAND")
    if command and command.strip():
        return _codex_token_from_command(command, values)
    return _codex_token_from_auth_file(values)


def _codex_token_from_command(command: str, values: Mapping[str, str]) -> str:
    try:
        timeout = float(values.get("TINYAGENT_CODEX_AUTH_COMMAND_TIMEOUT_SECONDS", "5"))
    except ValueError as exc:
        raise ProviderError("TINYAGENT_CODEX_AUTH_COMMAND_TIMEOUT_SECONDS must be a number.") from exc
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ProviderError(f"TINYAGENT_CODEX_AUTH_COMMAND is invalid: {exc}") from exc
    if not argv:
        raise ProviderError("TINYAGENT_CODEX_AUTH_COMMAND cannot be empty.")
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProviderError(f"Codex auth command failed: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise ProviderError(f"Codex auth command failed: {detail}")
    token = result.stdout.strip()
    if not token:
        raise ProviderError("Codex auth command did not print a bearer token.")
    if any(char.isspace() for char in token):
        raise ProviderError("Codex auth command must print only the bearer token.")
    return token


def _codex_token_from_auth_file(values: Mapping[str, str]) -> str:
    auth_path = _codex_auth_path(values)
    if auth_path is None or not auth_path.is_file():
        raise ProviderError(
            "TINYAGENT_CODEX_BEARER_TOKEN, TINYAGENT_CODEX_AUTH_COMMAND, or a Codex auth.json file "
            "is required for openai-codex provider."
        )
    try:
        payload = json.loads(auth_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderError(f"Could not read Codex auth file: {exc}") from exc
    tokens = payload.get("tokens") if isinstance(payload, dict) else None
    access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
    if not isinstance(access_token, str) or not access_token.strip():
        raise ProviderError("Codex auth file does not contain tokens.access_token.")
    if _jwt_expiring(access_token, skew_seconds=60):
        raise ProviderError(
            "Codex access token is expired or near expiry. Run `codex` to refresh it, "
            "or set TINYAGENT_CODEX_AUTH_COMMAND to a refresh-aware token command."
        )
    return access_token.strip()


def _codex_auth_path(values: Mapping[str, str]) -> Path | None:
    explicit = values.get("TINYAGENT_CODEX_AUTH_FILE")
    if explicit:
        return Path(explicit).expanduser()
    codex_home = values.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser() / "auth.json"
    default = Path.home() / ".codex" / "auth.json"
    return default if default.exists() else None


def _jwt_expiring(token: str, *, skew_seconds: int) -> bool:
    parts = token.split(".")
    if len(parts) < 2:
        return False
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()).decode())
    except (ValueError, json.JSONDecodeError):
        return False
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    return float(exp) <= time.time() + skew_seconds


def _string_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True)


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _provider_error(message: str):
    return ProviderError(message)
