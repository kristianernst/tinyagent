from __future__ import annotations

from tinyagent.core.state import RunState, ToolCall, ToolResult, Workspace
from tinyagent.core.tool_recording import append_tool_step, record_tool_blocked, record_tool_result_event


def test_record_tool_result_event_emits_snapshot_before_terminal_and_bounds_data(tmp_path) -> None:
    state = RunState.create("tool recording", Workspace(tmp_path))
    call = ToolCall(name="shell", id="call_1")
    result = ToolResult(
        tool_name="shell",
        call_id="call_1",
        output="abcdef",
        ok=False,
        data={"captured_output_artifact": "artifacts/captured.txt", "large": "x" * 5_000, "output_tokens": 3},
        failure_kind="command_failed",
        read_hints=["artifacts/captured.txt"],
    )

    record_tool_result_event(state, call, result)

    snapshot, terminal = state.events
    assert snapshot.type == "tool.execution.output.snapshot"
    assert snapshot.data["output_tokens"] == 3
    assert snapshot.data["captured_output_artifact"] == "artifacts/captured.txt"
    assert terminal.type == "tool.execution.failed"
    assert terminal.data["output"] == "abcdef"
    assert terminal.data["output_tokens"] == 3
    assert terminal.data["output_truncated"] is True
    assert terminal.data["failure_kind"] == "command_failed"
    assert terminal.data["read_hints"] == ["artifacts/captured.txt"]
    assert terminal.data["data"]["_truncated"] is True


def test_record_cancelled_tool_result_emits_only_cancelled_terminal(tmp_path) -> None:
    state = RunState.create("tool recording", Workspace(tmp_path))
    call = ToolCall(name="shell", id="call_cancel")
    result = ToolResult(
        tool_name="shell",
        call_id="call_cancel",
        output="cancelled",
        ok=False,
        data={"cancelled": True, "reason": "sigint"},
        failure_kind="unknown",
    )

    record_tool_result_event(state, call, result)

    assert [event.type for event in state.events] == ["tool.execution.cancelled"]
    assert state.events[0].data["reason"] == "sigint"


def test_append_tool_step_records_transcript_refs_observations_and_synthetic_flag(tmp_path) -> None:
    state = RunState.create("tool recording", Workspace(tmp_path))
    state.current_turn_id = "turn-1"
    call = ToolCall(name="shell", id="call_1")
    state.transcript.record_tool_call(
        item_id="transcript-tool-call-0001",
        turn_id=state.current_turn_id,
        model_call_id="model-call-1",
        tool_call_id=call.id,
        tool_name=call.name,
        args={"cmd": "printf ok"},
    )
    result = ToolResult(
        tool_name="shell",
        call_id=call.id,
        output="blocked",
        ok=False,
        data={
            "blocked": True,
            "output_artifact": "artifacts/output.txt",
            "captured_output_artifact": "artifacts/captured.txt",
        },
        artifact_path="artifacts/tool.txt",
        failure_kind="policy_denied",
    )

    append_tool_step(state, call, result)

    assert state.transcript.pending_tool_call_ids == set()
    tool_result = state.transcript.items[-1]
    assert tool_result.kind == "tool_result"
    assert tool_result.artifact_refs == ("artifacts/tool.txt", "artifacts/output.txt", "artifacts/captured.txt")
    assert tool_result.data["synthetic"] is True
    assert state.tool_steps[0].call == call
    assert state.observations
    assert state.observations[0].refs == ("artifacts/tool.txt", "artifacts/output.txt", "artifacts/captured.txt")
    assert state.observations[0].data["tool_call_id"] == "call_1"
    assert state.events[-1].type == "observation.recorded"


def test_record_tool_blocked_event_payload(tmp_path) -> None:
    state = RunState.create("tool recording", Workspace(tmp_path))
    call = ToolCall(name="shell", id="call_blocked")

    record_tool_blocked(state, call, "denied")

    assert state.events[0].type == "tool.execution.blocked"
    assert state.events[0].data == {"tool_call_id": "call_blocked", "tool": "shell", "reason": "denied"}
