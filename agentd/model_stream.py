"""Model streaming deltas, assembly, and provider chunk parsing."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from agentd.events import utc_now
from agentd.state import Message, ModelResponse, RunState, ToolCall

ModelDeltaKind = Literal[
    "text_delta",
    "reasoning_summary_delta",
    "reasoning_visible_delta",
    "reasoning_encrypted",
    "tool_call_started",
    "tool_call_args_delta",
    "tool_call_completed",
    "output_item_started",
    "output_item_completed",
    "usage",
    "completed",
    "failed",
]


@dataclass(frozen=True)
class ProviderStreamEvent:
    provider: str
    type: str
    raw: dict[str, Any]
    received_at: str = field(default_factory=lambda: utc_now().isoformat().replace("+00:00", "Z"))


@dataclass(frozen=True)
class ModelDelta:
    kind: ModelDeltaKind
    item_id: str | None = None
    tool_call_id: str | None = None
    delta: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class ModelResponseAssembler:
    def __init__(self, *, provider: str) -> None:
        self.provider = provider
        self.content_parts: list[str] = []
        self.tool_calls: dict[str, _StreamToolCall] = {}
        self.tool_order: list[str] = []
        self.finish_reason: str | None = None
        self.usage: dict[str, Any] = {}

    def accept(self, delta: ModelDelta) -> None:
        match delta.kind:
            case "text_delta":
                self.content_parts.append(delta.delta)
            case "tool_call_started":
                self._tool_call_for(delta)
            case "tool_call_args_delta":
                tool_call = self._tool_call_for(delta)
                tool_call.arguments.append(delta.delta)
            case "tool_call_completed":
                self._tool_call_for(delta).completed = True
            case "usage":
                self.usage.update(delta.data)
            case "completed":
                finish_reason = delta.data.get("finish_reason")
                self.finish_reason = str(finish_reason) if finish_reason is not None else self.finish_reason
            case "failed":
                reason = delta.data.get("reason") or "stream failed"
                raise _provider_error(str(reason))
            case _:
                return

    def response(self) -> ModelResponse:
        raw: dict[str, Any] = {"streamed": True}
        if self.usage:
            raw["usage"] = self.usage
        return ModelResponse(
            content="".join(self.content_parts),
            tool_calls=tuple(self._assembled_tool_call(key) for key in self.tool_order),
            finish_reason=self.finish_reason,
            raw=raw,
        )

    def _tool_call_for(self, delta: ModelDelta) -> _StreamToolCall:
        key = _stream_tool_key(delta)
        if key not in self.tool_calls:
            self.tool_calls[key] = _StreamToolCall()
            self.tool_order.append(key)
        tool_call = self.tool_calls[key]
        if delta.tool_call_id and not delta.tool_call_id.startswith("index_"):
            tool_call.id = delta.tool_call_id
        name = delta.data.get("name")
        if isinstance(name, str) and name:
            tool_call.name = name
        provider_id = delta.data.get("id")
        if isinstance(provider_id, str) and provider_id:
            tool_call.id = provider_id
        return tool_call

    def _assembled_tool_call(self, key: str) -> ToolCall:
        tool_call = self.tool_calls[key]
        if not tool_call.name:
            raise _provider_error("Tool call is missing function.name.")
        raw_arguments = "".join(tool_call.arguments) or "{}"
        try:
            args = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise _provider_error(f"Tool call arguments for {tool_call.name} are invalid JSON.") from exc
        if not isinstance(args, dict):
            raise _provider_error(f"Tool call arguments for {tool_call.name} must be a JSON object.")
        if tool_call.id:
            return ToolCall(id=tool_call.id, name=tool_call.name, args=args)
        return ToolCall(name=tool_call.name, args=args)


@dataclass
class _StreamToolCall:
    id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=list)
    completed: bool = False


def complete_model_call(
    model: Any,
    messages: Sequence[Message],
    tools: Sequence[Any],
    state: RunState,
    *,
    stream: bool,
    call_index: int,
) -> ModelResponse:
    if not stream:
        return model.complete(messages, tools, state)
    stream_method = getattr(model, "stream", None)
    if not callable(stream_method):
        return model.complete(messages, tools, state)

    state.emit("model.stream.started", {"provider": model.name, "turn": call_index})
    assembler = ModelResponseAssembler(provider=model.name)
    trace = _StreamTraceState()
    for delta in stream_method(messages, tools, state):
        _record_model_delta(state, model.name, trace.normalize(delta))
        assembler.accept(delta)
    return assembler.response()


def assemble_model_deltas(provider: str, deltas: Iterable[ModelDelta]) -> ModelResponse:
    assembler = ModelResponseAssembler(provider=provider)
    for delta in deltas:
        assembler.accept(delta)
    return assembler.response()


def model_response_to_deltas(response: ModelResponse) -> Iterator[ModelDelta]:
    if response.content:
        yield ModelDelta(kind="text_delta", delta=response.content)
    for call in response.tool_calls:
        yield ModelDelta(
            kind="tool_call_started",
            tool_call_id=call.id,
            data={"id": call.id, "name": call.name, "type": "function"},
        )
        yield ModelDelta(
            kind="tool_call_args_delta",
            tool_call_id=call.id,
            delta=json.dumps(call.args, sort_keys=True),
            data={"id": call.id, "name": call.name},
        )
        yield ModelDelta(
            kind="tool_call_completed",
            tool_call_id=call.id,
            data={"id": call.id, "name": call.name},
        )
    if response.raw.get("usage") and isinstance(response.raw["usage"], dict):
        yield ModelDelta(kind="usage", data=response.raw["usage"])
    yield ModelDelta(kind="completed", data={"finish_reason": response.finish_reason})


def parse_chat_completion(raw: dict[str, Any]) -> ModelResponse:
    try:
        choice = raw["choices"][0]
        message = choice.get("message", {})
    except (KeyError, IndexError, TypeError) as exc:
        raise _provider_error("Model provider response did not include choices[0].message.") from exc

    return ModelResponse(
        content=message.get("content") or "",
        tool_calls=tuple(_parse_tool_call(call) for call in message.get("tool_calls") or []),
        finish_reason=choice.get("finish_reason"),
        raw=raw,
    )


def parse_chat_completion_chunk(raw: dict[str, Any]) -> Iterator[ModelDelta]:
    usage = raw.get("usage")
    if isinstance(usage, dict):
        yield ModelDelta(kind="usage", data=usage)
    for choice in raw.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str) and content:
            yield ModelDelta(kind="text_delta", delta=content, data={"provider_chunk_id": raw.get("id")})
        reasoning_content = delta.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content:
            yield ModelDelta(
                kind="reasoning_visible_delta",
                delta=reasoning_content,
                data={
                    "provider_chunk_id": raw.get("id"),
                    "provider_field": "reasoning_content",
                },
            )
        for call in delta.get("tool_calls") or []:
            if isinstance(call, dict):
                yield from _parse_chat_tool_call_delta(call)
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None:
            yield ModelDelta(kind="completed", data={"finish_reason": finish_reason})


def _record_model_delta(state: RunState, provider: str, delta: ModelDelta) -> None:
    match delta.kind:
        case "text_delta":
            state.emit(
                "model.text.delta",
                {"delta": delta.delta, "chars": len(delta.delta), "item_id": delta.item_id},
                visibility="user",
                durability="ephemeral",
                item_id=delta.item_id,
            )
        case "reasoning_summary_delta":
            safe_to_display = delta.data.get("safe_to_display", True)
            state.emit(
                "reasoning.summary.delta",
                _reasoning_event_data(delta, include_delta=safe_to_display),
                visibility="user" if safe_to_display else "debug",
                durability="ephemeral",
                item_id=delta.item_id,
            )
        case "reasoning_visible_delta":
            state.emit(
                "reasoning.visible.delta",
                _reasoning_event_data(delta, include_delta=True),
                visibility="internal",
                durability="ephemeral",
                item_id=delta.item_id,
            )
        case "reasoning_encrypted":
            state.emit(
                "reasoning.encrypted",
                {"chars": len(delta.delta)},
                visibility="internal",
                durability="ephemeral",
                item_id=delta.item_id,
            )
        case "tool_call_started":
            return
        case "tool_call_args_delta":
            state.emit(
                "tool.args.delta",
                {
                    "tool_call_id": delta.tool_call_id,
                    "tool": delta.data.get("name"),
                    "chars": len(delta.delta),
                    "delta": delta.delta,
                },
                durability="ephemeral",
            )
        case "usage":
            state.emit("model.usage", {"provider": provider, **delta.data})
        case _:
            return


def _reasoning_event_data(delta: ModelDelta, *, include_delta: bool) -> dict[str, Any]:
    data = {"chars": len(delta.delta), "item_id": delta.item_id}
    if include_delta:
        data["delta"] = delta.delta
    provider_field = delta.data.get("provider_field")
    if isinstance(provider_field, str) and provider_field:
        data["provider_field"] = provider_field
    return data


def _parse_chat_tool_call_delta(call: dict[str, Any]) -> Iterator[ModelDelta]:
    function = call.get("function") or {}
    index = call.get("index")
    call_id = call.get("id")
    stream_id = str(call_id) if call_id else f"index_{index}" if index is not None else "index_0"
    data = {
        "index": index,
        "id": call_id,
        "name": function.get("name"),
        "type": call.get("type"),
    }
    if call_id or function.get("name"):
        yield ModelDelta(kind="tool_call_started", tool_call_id=stream_id, data=data)
    arguments = function.get("arguments")
    if isinstance(arguments, str) and arguments:
        yield ModelDelta(kind="tool_call_args_delta", tool_call_id=stream_id, delta=arguments, data=data)


def _parse_tool_call(call: dict[str, Any]) -> ToolCall:
    function = call.get("function") or {}
    name = function.get("name")
    if not name:
        raise _provider_error("Tool call is missing function.name.")
    raw_arguments = function.get("arguments") or "{}"
    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise _provider_error(f"Tool call arguments for {name} are invalid JSON.") from exc
    if not isinstance(args, dict):
        raise _provider_error(f"Tool call arguments for {name} must be a JSON object.")
    call_id = call.get("id")
    if call_id:
        return ToolCall(id=call_id, name=name, args=args)
    return ToolCall(name=name, args=args)


def _stream_tool_key(delta: ModelDelta) -> str:
    index = delta.data.get("index")
    if isinstance(index, int):
        return f"index:{index}"
    if delta.tool_call_id:
        return delta.tool_call_id
    return "index:0"


class _StreamTraceState:
    def __init__(self) -> None:
        self.tool_call_ids: dict[str, str] = {}
        self.tool_names: dict[str, str] = {}

    def normalize(self, delta: ModelDelta) -> ModelDelta:
        if not delta.kind.startswith("tool_call_"):
            return delta

        key = _stream_tool_key(delta)
        provider_id = _provider_tool_call_id(delta)
        if provider_id:
            self.tool_call_ids[key] = provider_id
        name = delta.data.get("name")
        if isinstance(name, str) and name:
            self.tool_names[key] = name

        resolved_id = self.tool_call_ids.get(key, delta.tool_call_id)
        resolved_name = self.tool_names.get(key)
        data = dict(delta.data)
        if resolved_id and not data.get("id"):
            data["id"] = resolved_id
        if resolved_name and not data.get("name"):
            data["name"] = resolved_name
        return replace(delta, tool_call_id=resolved_id, data=data)


def _provider_tool_call_id(delta: ModelDelta) -> str:
    provider_id = delta.data.get("id")
    if isinstance(provider_id, str) and provider_id:
        return provider_id
    if delta.tool_call_id and not delta.tool_call_id.startswith("index_"):
        return delta.tool_call_id
    return ""


def _provider_error(message: str):
    from agentd.models import ProviderError

    return ProviderError(message)
