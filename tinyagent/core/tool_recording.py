"""Tool result recording helpers."""

from __future__ import annotations

from tinyagent.core.artifacts import tool_result_artifact_refs
from tinyagent.core.events import small_event_data
from tinyagent.core.observations import extract_observations
from tinyagent.core.state import RunState, ToolCall, ToolResult, ToolStep
from tinyagent.core.token_utils import clip_text_to_token_budget, estimate_tokens


def record_tool_result_event(state: RunState, call: ToolCall, result: ToolResult) -> None:
    if result.data.get("cancelled"):
        state.emit(
            "tool.execution.cancelled",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "reason": result.data.get("reason") or state.cancel_reason or "cancelled",
                "output": clip_text_to_token_budget(result.output, state.budgets.max_tool_output_tokens_visible),
                "output_tokens": _output_tokens(result),
                "artifact_path": result.artifact_path,
                "failure_kind": result.failure_kind or result.data.get("failure_kind"),
                "data": small_event_data(result.data),
            },
            visibility="user",
        )
        return
    output = clip_text_to_token_budget(result.output, state.budgets.max_tool_output_tokens_visible)
    output_tokens = _output_tokens(result)
    if tool_result_artifact_refs(result):
        state.emit(
            "tool.execution.output.snapshot",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "output_tokens": output_tokens,
                "artifact_path": result.artifact_path,
                "output_artifact": result.data.get("output_artifact"),
                "context_artifact": result.data.get("context_artifact"),
                "captured_output_artifact": result.data.get("captured_output_artifact"),
            },
        )
    payload = {
        "tool_call_id": call.id,
        "tool": call.name,
        "ok": result.ok,
        "blocked": bool(result.data.get("blocked")),
        "output": output,
        "output_tokens": output_tokens,
        "output_truncated": output_tokens > estimate_tokens(output),
        "data": small_event_data(result.data),
    }
    batch_id = result.metadata.get("batch_id")
    if isinstance(batch_id, str) and batch_id:
        payload["batch_id"] = batch_id
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
    state.transcript.record_tool_result(
        item_id=f"transcript-tool-result-{len(state.tool_steps) + 1:04d}",
        turn_id=state.current_turn_id,
        tool_call_id=result.call_id or call.id,
        tool_name=result.tool_name or call.name,
        ok=result.ok,
        summary=result.summary or _first_line(result.output) or ("ok" if result.ok else "failed"),
        failure_kind=result.failure_kind or result.data.get("failure_kind"),
        artifact_refs=tool_result_artifact_refs(result),
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


def _output_tokens(result: ToolResult) -> int:
    value = result.data.get("output_tokens")
    if isinstance(value, int):
        return value
    return estimate_tokens(result.output)
