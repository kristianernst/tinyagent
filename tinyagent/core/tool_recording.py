"""Tool result recording helpers."""

from __future__ import annotations

from tinyagent.core.events import small_event_data
from tinyagent.core.observations import extract_observations
from tinyagent.core.state import RunState, ToolCall, ToolResult, ToolStep


def record_tool_result_event(state: RunState, call: ToolCall, result: ToolResult) -> None:
    if result.data.get("cancelled"):
        state.emit(
            "tool.execution.cancelled",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "reason": result.data.get("reason") or state.cancel_reason or "cancelled",
                "output": result.output[: state.budgets.max_command_output_chars_visible],
                "output_chars": _output_chars(result),
                "artifact_path": result.artifact_path,
                "failure_kind": result.failure_kind or result.data.get("failure_kind"),
                "data": small_event_data(result.data),
            },
            visibility="user",
        )
        return
    output_limit = state.budgets.max_command_output_chars_visible
    output = result.output[:output_limit]
    output_chars = _output_chars(result)
    if result.artifact_path or result.data.get("output_artifact"):
        state.emit(
            "tool.execution.output.snapshot",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "output_chars": output_chars,
                "artifact_path": result.artifact_path,
                "output_artifact": result.data.get("output_artifact"),
                "context_artifact": result.data.get("context_artifact"),
            },
        )
    payload = {
        "tool_call_id": call.id,
        "tool": call.name,
        "ok": result.ok,
        "blocked": bool(result.data.get("blocked")),
        "output": output,
        "output_chars": output_chars,
        "output_truncated": output_chars > len(output),
        "data": small_event_data(result.data),
    }
    if result.artifact_path:
        payload["artifact_path"] = result.artifact_path
    failure_kind = result.failure_kind or result.data.get("failure_kind")
    if failure_kind:
        payload["failure_kind"] = failure_kind
    for key in ("capability", "source", "recoverability"):
        value = result.data.get(key)
        if value:
            payload[key] = value
    if result.read_hints:
        payload["read_hints"] = result.read_hints
    state.emit("tool.execution.completed" if result.ok else "tool.execution.failed", payload, visibility="user")


def append_tool_step(state: RunState, call: ToolCall, result: ToolResult) -> None:
    artifact_refs = tuple(
        ref
        for ref in (
            result.artifact_path,
            result.data.get("context_artifact"),
            result.data.get("output_artifact"),
        )
        if isinstance(ref, str) and ref
    )
    state.transcript.record_tool_result(
        item_id=f"transcript-tool-result-{len(state.tool_steps) + 1:04d}",
        turn_id=state.current_turn_id,
        tool_call_id=result.call_id or call.id,
        tool_name=result.tool_name or call.name,
        ok=result.ok,
        summary=result.summary or _first_line(result.output) or ("ok" if result.ok else "failed"),
        failure_kind=result.failure_kind or result.data.get("failure_kind"),
        artifact_refs=artifact_refs,
        synthetic=bool(result.data.get("blocked") or result.data.get("progress_blocked")),
        data={
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "truncated": result.truncated,
        },
    )
    state.tool_steps.append(ToolStep(call=call, result=result))
    for observation in extract_observations(call, result, state):
        observation.data.setdefault("tool_call_id", call.id)
        state.observations.append(observation)
        state.emit(
            "observation.recorded",
            observation.to_json_dict(),
            artifact_refs=list(observation.refs),
        )


def record_tool_blocked(state: RunState, call: ToolCall, reason: str) -> None:
    state.emit(
        "tool.execution.blocked",
        {
            "tool_call_id": call.id,
            "tool": call.name,
            "reason": reason,
        },
        visibility="user",
    )


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0][:240] if text.strip() else ""


def _output_chars(result: ToolResult) -> int:
    value = result.data.get("output_chars")
    return value if isinstance(value, int) else len(result.output)
