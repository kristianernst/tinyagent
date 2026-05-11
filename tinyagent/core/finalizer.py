"""Run artifact and terminal-event finalization."""

from __future__ import annotations

from tinyagent.core.contextfs import refresh_contextfs
from tinyagent.core.output import capture_final_diff, write_final_text
from tinyagent.core.state import RunState


def finalize_artifacts(state: RunState, *, contextfs_enabled: bool) -> None:
    state.finalization_attempted = True
    state.start_step("artifact_finalization", "artifact-finalization-0001")
    state.emit("artifact.finalization.started", {"output_dir": str(state.output_dir)})
    try:
        _finalize_message(state)
        capture_final_diff(state)
        for path in ("final.md", "metrics.json", "final.diff"):
            state.emit("artifact.materialized", {"path": path, "kind": "run_output"}, visibility="user")
        state.emit("artifact.finalization.completed", {"output_dir": str(state.output_dir)})
        state.finish_step("completed")
    except Exception as exc:  # pragma: no cover - defensive finalization boundary
        state.emit("artifact.finalization.failed", {"reason": str(exc)}, visibility="user")
        state.finish_step("failed", data={"reason": str(exc)})
        if not state.failed and not state.cancelled:
            state.fail(f"artifact finalization failed: {exc}")
    finally:
        if contextfs_enabled:
            index_path = refresh_contextfs(state)
            state.emit("contextfs.index.updated", {"path": index_path, "phase": "finalization"})


def finalize_run(state: RunState, *, contextfs_enabled: bool) -> None:
    event_type = "run.cancelled" if state.cancelled else "run.failed" if state.failed else "run.completed"
    if any(event.type == event_type for event in state.events):
        return
    data = {
        "status": "cancelled" if state.cancelled else "failed" if state.failed else "completed",
        "turn_count": state.turn_count,
        "model_call_count": state.model_call_count,
        "tool_call_count": state.tool_call_count,
        "final_output_chars": len(state.final_output),
        "duration_seconds": state.elapsed_seconds(),
        "workspace_mode": state.workspace_envelope.mode if state.workspace_envelope else None,
        "workspace_effective_mode": state.workspace_envelope.effective_mode if state.workspace_envelope else None,
        "approval_mode": state.approval_mode,
        "sandbox_mode": state.workspace_envelope.sandbox_mode if state.workspace_envelope else "none",
        "sandbox_backend": state.workspace_envelope.sandbox_backend if state.workspace_envelope else "none",
        "network_mode": state.workspace_envelope.network_mode if state.workspace_envelope else "deny",
        "sandbox_enforced": state.workspace_envelope.sandbox_enforced if state.workspace_envelope else False,
        "finalization_attempted": state.finalization_attempted,
    }
    if state.cancelled:
        data["reason"] = state.cancel_reason or "cancelled"
        data["current_step_kind"] = state.current_step_kind
        data["current_step_id"] = state.current_step_id
        data["escalated"] = state.cancel_escalated
        data["signal_count"] = max(state.cancel_signal_count, state.cancel_token.signal_count)
    if state.failed:
        data["reason"] = state.failure_reason or "Unknown failure"
    if state.cancelled:
        state.status = "cancelled"
    state.emit(event_type, data)
    if contextfs_enabled:
        refresh_contextfs(state)


def _finalize_message(state: RunState) -> None:
    if not state.done and not state.failed and not state.cancelled:
        state.finish("Run finished without explicit final output.")
    if not state.final_output:
        return
    if any(
        event.type == "model.message.completed" and event.data.get("output_path") == "final.md"
        for event in state.events
    ):
        return
    write_final_text(state)
    state.emit(
        "model.message.completed",
        {
            "role": "assistant",
            "content_chars": len(state.final_output),
            "output_path": "final.md",
        },
        visibility="user",
    )
