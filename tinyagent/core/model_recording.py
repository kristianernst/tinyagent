"""Model response recording helpers."""

from __future__ import annotations

from collections.abc import Sequence

from tinyagent.core.events import small_event_data
from tinyagent.core.state import RunState, ToolCall


def record_model_tool_calls(
    state: RunState,
    tool_calls: Sequence[ToolCall],
    *,
    provider: str,
    model_call_id: str,
    model_call_index: int,
) -> str | None:
    seen_current_call_ids: set[str] = set()
    for call in tool_calls:
        if call.id in seen_current_call_ids:
            return _fail_duplicate_tool_call(
                state,
                provider=provider,
                model_call_id=model_call_id,
                model_call_index=model_call_index,
                call=call,
            )
        seen_current_call_ids.add(call.id)

        completed_assemblies = (
            event
            for event in state.events
            if event.type == "model.tool_call.assembly.completed" and event.data.get("tool_call_id") == call.id
        )
        event_recorded = False
        for event in completed_assemblies:
            if event.data.get("model_call_id") != model_call_id:
                return _fail_duplicate_tool_call(
                    state,
                    provider=provider,
                    model_call_id=model_call_id,
                    model_call_index=model_call_index,
                    call=call,
                )
            event_recorded = True
        if not event_recorded:
            state.emit(
                "model.tool_call.assembly.started",
                {
                    "provider": provider,
                    "model_call_id": model_call_id,
                    "model_call_index": model_call_index,
                    "tool_call_id": call.id,
                    "tool": call.name,
                },
                visibility="user",
            )
            state.emit(
                "model.tool_call.assembly.completed",
                {
                    "provider": provider,
                    "model_call_id": model_call_id,
                    "model_call_index": model_call_index,
                    "tool_call_id": call.id,
                    "tool": call.name,
                    "args": small_event_data(call.args),
                },
                visibility="user",
            )
        transcript_recorded = any(
            item.kind == "tool_call" and item.tool_call_id == call.id
            for item in state.transcript.items
        )
        if not transcript_recorded:
            state.transcript.record_tool_call(
                item_id=f"transcript-tool-call-{len(state.transcript.items) + 1:04d}",
                turn_id=state.current_turn_id,
                model_call_id=model_call_id,
                tool_call_id=call.id,
                tool_name=call.name,
                args=small_event_data(call.args),
            )
    return None


def _fail_duplicate_tool_call(
    state: RunState,
    *,
    provider: str,
    model_call_id: str,
    model_call_index: int,
    call: ToolCall,
) -> str:
    reason = f"duplicate tool_call_id in run: {call.id}"
    state.emit(
        "model.tool_call.assembly.failed",
        {
            "provider": provider,
            "model_call_id": model_call_id,
            "model_call_index": model_call_index,
            "tool_call_id": call.id,
            "tool": call.name,
            "reason": reason,
        },
        visibility="user",
    )
    return reason
