from __future__ import annotations

from dataclasses import replace

from tinyagent.core.events import Event
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import LocalPolicy
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.state import ModelResponse, ToolCall
from tinyagent.core.tools import default_tools
from tinyagent.evals.invariants import check_event_invariants


def test_event_invariants_for_simple_final_response(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("simple final", workspace=tmp_path, run_id="run_event_simple")

    assert check_event_invariants(state.events) == []


def test_event_invariants_for_policy_denied_tool(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "curl https://example.com"}),)),
                ModelResponse(content="network denied", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("policy denied", workspace=tmp_path, run_id="run_event_policy_denied")

    assert check_event_invariants(state.events) == []


def test_event_invariants_for_default_denied_unknown_shell(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "printf ok"}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("shell run", workspace=tmp_path, run_id="run_event_shell")

    assert check_event_invariants(state.events) == []


def test_event_invariants_catch_artificial_sequence_violation(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("simple final", workspace=tmp_path, run_id="run_event_bad_seq")
    broken = list(state.events)
    broken[1] = replace(broken[1], seq=broken[0].seq)

    assert "event seq must be strictly increasing" in check_event_invariants(broken)


def test_event_invariants_catch_unclosed_step() -> None:
    events = [
        Event(type="run.started", run_id="run_bad", seq=1),
        Event(type="step.started", run_id="run_bad", seq=2, data={"step_id": "step-1"}),
        Event(type="run.completed", run_id="run_bad", seq=3),
    ]

    failures = check_event_invariants(events)

    assert "run terminal with open steps: ['step-1']" in failures


def test_event_invariants_catch_unsafe_artifact_path() -> None:
    events = [
        Event(type="run.started", run_id="run_bad", seq=1),
        Event(type="artifact.created", run_id="run_bad", seq=2, data={"path": "../escape.txt"}),
        Event(type="run.completed", run_id="run_bad", seq=3),
    ]

    assert "artifact path escapes run output: ../escape.txt" in check_event_invariants(events)


def test_event_invariants_catch_empty_top_level_and_nested_artifact_paths() -> None:
    direct = [
        Event(type="run.started", run_id="run_bad_empty_artifact", seq=1),
        Event(type="artifact.created", run_id="run_bad_empty_artifact", seq=2, data={"path": ""}),
        Event(type="run.completed", run_id="run_bad_empty_artifact", seq=3),
    ]
    nested = [
        Event(type="run.started", run_id="run_bad_nested_empty_artifact", seq=1),
        Event(
            type="tool.execution.completed",
            run_id="run_bad_nested_empty_artifact",
            seq=2,
            data={"tool_call_id": "call-1", "tool": "shell", "ok": True, "data": {"output_artifact": ""}},
        ),
        Event(type="artifact.finalization.started", run_id="run_bad_nested_empty_artifact", seq=3),
        Event(type="artifact.finalization.completed", run_id="run_bad_nested_empty_artifact", seq=4),
        Event(type="run.completed", run_id="run_bad_nested_empty_artifact", seq=5),
    ]

    for events in (direct, nested):
        assert "artifact path escapes run output: " in check_event_invariants(events)


def test_event_invariants_do_not_treat_generic_path_as_artifact_path() -> None:
    events = [
        Event(type="run.started", run_id="run_workspace_path", seq=1),
        Event(type="file.read", run_id="run_workspace_path", seq=2, data={"path": "/workspace/app.py"}),
        Event(type="artifact.finalization.started", run_id="run_workspace_path", seq=3),
        Event(type="artifact.finalization.completed", run_id="run_workspace_path", seq=4),
        Event(type="run.completed", run_id="run_workspace_path", seq=5),
    ]

    assert check_event_invariants(events) == []


def test_event_invariants_allow_run_scoped_approval_grant_reuse() -> None:
    events = [
        Event(type="run.started", run_id="run_approval", seq=1),
        Event(type="approval.requested", run_id="run_approval", seq=2, data={"approval_id": "approval-1"}),
        Event(
            type="approval.resolved",
            run_id="run_approval",
            seq=3,
            data={"approval_id": "approval-1", "decision": "approved", "scope": "run"},
        ),
        Event(
            type="approval.resolved",
            run_id="run_approval",
            seq=4,
            data={"approval_id": "approval-2", "decision": "approved", "scope": "run", "reason": "approval_grant"},
        ),
        Event(type="artifact.finalization.started", run_id="run_approval", seq=5),
        Event(type="artifact.finalization.completed", run_id="run_approval", seq=6),
        Event(type="run.completed", run_id="run_approval", seq=7),
    ]

    assert check_event_invariants(events) == []


def test_event_invariants_catch_model_tool_call_without_result() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_tool", seq=1),
        Event(type="model.call.started", run_id="run_bad_tool", seq=2, data={"model_call_id": "model-call-1"}),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_bad_tool",
            seq=3,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell"},
        ),
        Event(type="model.call.completed", run_id="run_bad_tool", seq=4, data={"model_call_id": "model-call-1"}),
        Event(type="run.completed", run_id="run_bad_tool", seq=5),
    ]

    assert "model tool call has no terminal tool result: call-1" in check_event_invariants(events)


def test_event_invariants_catch_model_tool_count_mismatch() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_tool_count", seq=1),
        Event(type="model.call.started", run_id="run_bad_tool_count", seq=2, data={"model_call_id": "model-call-1"}),
        Event(
            type="model.call.completed",
            run_id="run_bad_tool_count",
            seq=3,
            data={"model_call_id": "model-call-1", "tool_call_count": 1},
        ),
        Event(type="artifact.finalization.started", run_id="run_bad_tool_count", seq=4),
        Event(type="artifact.finalization.completed", run_id="run_bad_tool_count", seq=5),
        Event(type="run.completed", run_id="run_bad_tool_count", seq=6),
    ]

    assert "model call tool_call_count mismatch: model-call-1 expected 1, saw 0 completed assembly event(s)" in check_event_invariants(
        events
    )


def test_event_invariants_catch_malformed_model_tool_assembly() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_assembly", seq=1),
        Event(type="model.call.started", run_id="run_bad_assembly", seq=2, data={"model_call_id": "model-call-1"}),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_bad_assembly",
            seq=3,
            data={"tool_call_id": "call-1", "tool": "shell"},
        ),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_bad_assembly",
            seq=4,
            data={"model_call_id": "model-call-1", "tool": "shell"},
        ),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_bad_assembly",
            seq=5,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-2"},
        ),
        Event(
            type="model.call.completed",
            run_id="run_bad_assembly",
            seq=6,
            data={"model_call_id": "model-call-1", "tool_call_count": 0},
        ),
        Event(type="artifact.finalization.started", run_id="run_bad_assembly", seq=7),
        Event(type="artifact.finalization.completed", run_id="run_bad_assembly", seq=8),
        Event(type="run.completed", run_id="run_bad_assembly", seq=9),
    ]

    failures = check_event_invariants(events)

    assert "model tool assembly completed missing model_call_id: call-1" in failures
    assert "model tool assembly completed missing tool_call_id: model-call-1" in failures
    assert "model tool assembly completed missing tool: call-2" in failures


def test_event_invariants_catch_duplicate_model_tool_call_assembly() -> None:
    events = [
        Event(type="run.started", run_id="run_duplicate_tool", seq=1),
        Event(type="model.call.started", run_id="run_duplicate_tool", seq=2, data={"model_call_id": "model-call-1"}),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_duplicate_tool",
            seq=3,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell"},
        ),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_duplicate_tool",
            seq=4,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell"},
        ),
        Event(type="model.call.completed", run_id="run_duplicate_tool", seq=5, data={"model_call_id": "model-call-1"}),
        Event(type="policy.evaluated", run_id="run_duplicate_tool", seq=6, data={"tool_call_id": "call-1"}),
        Event(type="tool.execution.blocked", run_id="run_duplicate_tool", seq=7, data={"tool_call_id": "call-1"}),
        Event(
            type="tool.execution.failed",
            run_id="run_duplicate_tool",
            seq=8,
            data={"tool_call_id": "call-1", "tool": "shell", "ok": False, "blocked": True},
        ),
        Event(type="artifact.finalization.started", run_id="run_duplicate_tool", seq=9),
        Event(type="artifact.finalization.completed", run_id="run_duplicate_tool", seq=10),
        Event(type="run.completed", run_id="run_duplicate_tool", seq=11),
    ]

    assert "model tool call assembled more than once: call-1" in check_event_invariants(events)


def test_event_invariants_do_not_add_ordering_noise_for_duplicate_late_assembly() -> None:
    events = [
        Event(type="run.started", run_id="run_duplicate_late", seq=1),
        Event(type="model.call.started", run_id="run_duplicate_late", seq=2, data={"model_call_id": "model-call-1"}),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_duplicate_late",
            seq=3,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell"},
        ),
        Event(type="model.call.completed", run_id="run_duplicate_late", seq=4, data={"model_call_id": "model-call-1"}),
        Event(type="policy.evaluated", run_id="run_duplicate_late", seq=5, data={"tool_call_id": "call-1"}),
        Event(type="tool.execution.started", run_id="run_duplicate_late", seq=6, data={"tool_call_id": "call-1", "tool": "shell"}),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_duplicate_late",
            seq=7,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell"},
        ),
        Event(
            type="tool.execution.completed",
            run_id="run_duplicate_late",
            seq=8,
            data={"tool_call_id": "call-1", "tool": "shell", "ok": True},
        ),
        Event(type="artifact.finalization.started", run_id="run_duplicate_late", seq=9),
        Event(type="artifact.finalization.completed", run_id="run_duplicate_late", seq=10),
        Event(type="run.completed", run_id="run_duplicate_late", seq=11),
    ]

    failures = check_event_invariants(events)

    assert "model tool call assembled more than once: call-1" in failures
    assert "tool execution started before model assembly completed: call-1" not in failures


def test_event_invariants_catch_tool_execution_before_model_call_completed() -> None:
    events = [
        Event(type="run.started", run_id="run_early_tool", seq=1),
        Event(type="model.call.started", run_id="run_early_tool", seq=2, data={"model_call_id": "model-call-1"}),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_early_tool",
            seq=3,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell", "args": {"cmd": "true"}},
        ),
        Event(type="policy.evaluated", run_id="run_early_tool", seq=4, data={"tool_call_id": "call-1"}),
        Event(
            type="tool.execution.started",
            run_id="run_early_tool",
            seq=5,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell"},
        ),
        Event(
            type="tool.execution.completed",
            run_id="run_early_tool",
            seq=6,
            data={"tool_call_id": "call-1", "tool": "shell", "ok": True},
        ),
        Event(
            type="model.call.completed",
            run_id="run_early_tool",
            seq=7,
            data={"model_call_id": "model-call-1", "tool_call_count": 1},
        ),
        Event(type="artifact.finalization.started", run_id="run_early_tool", seq=8),
        Event(type="artifact.finalization.completed", run_id="run_early_tool", seq=9),
        Event(type="run.completed", run_id="run_early_tool", seq=10),
    ]

    failures = check_event_invariants(events)

    assert "tool execution started before model call completed: call-1" in failures
    assert "model tool call has no terminal tool result: call-1" not in failures


def test_event_invariants_catch_result_without_model_tool_call() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_result", seq=1),
        Event(
            type="tool.execution.completed",
            run_id="run_bad_result",
            seq=2,
            data={"tool_call_id": "call-1", "tool": "shell", "ok": True},
        ),
        Event(type="artifact.finalization.started", run_id="run_bad_result", seq=3),
        Event(type="artifact.finalization.completed", run_id="run_bad_result", seq=4),
        Event(type="run.completed", run_id="run_bad_result", seq=5),
    ]

    failures = check_event_invariants(events)

    assert "tool execution terminal without model tool assembly: call-1" in failures
    assert "tool execution terminal without start: call-1" in failures


def test_event_invariants_require_output_snapshot_before_artifact_tool_terminal() -> None:
    events = [
        Event(type="run.started", run_id="run_missing_snapshot", seq=1),
        Event(type="model.call.started", run_id="run_missing_snapshot", seq=2, data={"model_call_id": "model-call-1"}),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_missing_snapshot",
            seq=3,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell", "args": {"cmd": "true"}},
        ),
        Event(
            type="model.call.completed",
            run_id="run_missing_snapshot",
            seq=4,
            data={"model_call_id": "model-call-1", "tool_call_count": 1},
        ),
        Event(type="policy.evaluated", run_id="run_missing_snapshot", seq=5, data={"tool_call_id": "call-1"}),
        Event(type="tool.execution.started", run_id="run_missing_snapshot", seq=6, data={"tool_call_id": "call-1", "tool": "shell"}),
        Event(
            type="tool.execution.completed",
            run_id="run_missing_snapshot",
            seq=7,
            data={"tool_call_id": "call-1", "tool": "shell", "ok": True, "artifact_path": "artifacts/tool.txt"},
        ),
        Event(type="artifact.finalization.started", run_id="run_missing_snapshot", seq=8),
        Event(type="artifact.finalization.completed", run_id="run_missing_snapshot", seq=9),
        Event(type="run.completed", run_id="run_missing_snapshot", seq=10),
    ]

    assert "tool execution artifact output without snapshot: call-1" in check_event_invariants(events)


def test_event_invariants_require_output_snapshot_before_artifact_tool_terminal_order() -> None:
    events = [
        Event(type="run.started", run_id="run_late_snapshot", seq=1),
        Event(type="model.call.started", run_id="run_late_snapshot", seq=2, data={"model_call_id": "model-call-1"}),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_late_snapshot",
            seq=3,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell", "args": {"cmd": "true"}},
        ),
        Event(
            type="model.call.completed",
            run_id="run_late_snapshot",
            seq=4,
            data={"model_call_id": "model-call-1", "tool_call_count": 1},
        ),
        Event(type="policy.evaluated", run_id="run_late_snapshot", seq=5, data={"tool_call_id": "call-1"}),
        Event(type="tool.execution.started", run_id="run_late_snapshot", seq=6, data={"tool_call_id": "call-1", "tool": "shell"}),
        Event(
            type="tool.execution.failed",
            run_id="run_late_snapshot",
            seq=7,
            data={
                "tool_call_id": "call-1",
                "tool": "shell",
                "ok": False,
                "data": {"captured_output_artifact": "artifacts/output.txt"},
            },
        ),
        Event(type="tool.execution.output.snapshot", run_id="run_late_snapshot", seq=8, data={"tool_call_id": "call-1"}),
        Event(type="artifact.finalization.started", run_id="run_late_snapshot", seq=9),
        Event(type="artifact.finalization.completed", run_id="run_late_snapshot", seq=10),
        Event(type="run.completed", run_id="run_late_snapshot", seq=11),
    ]

    assert "tool execution output snapshot after terminal: call-1" in check_event_invariants(events)


def test_event_invariants_catch_workspace_delta_completion_without_start() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_delta", seq=1),
        Event(type="workspace.delta.completed", run_id="run_bad_delta", seq=2, data={"tool_call_id": "call-1"}),
        Event(type="artifact.finalization.started", run_id="run_bad_delta", seq=3),
        Event(type="artifact.finalization.completed", run_id="run_bad_delta", seq=4),
        Event(type="run.completed", run_id="run_bad_delta", seq=5),
    ]

    assert "workspace delta completed without start: call-1" in check_event_invariants(events)


def test_event_invariants_catch_open_workspace_mutation() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_mutation", seq=1),
        Event(type="workspace.mutation.planned", run_id="run_bad_mutation", seq=2, data={"tool_call_id": "call-1"}),
        Event(type="workspace.mutation.started", run_id="run_bad_mutation", seq=3, data={"tool_call_id": "call-1"}),
        Event(type="artifact.finalization.started", run_id="run_bad_mutation", seq=4),
        Event(type="artifact.finalization.completed", run_id="run_bad_mutation", seq=5),
        Event(type="run.completed", run_id="run_bad_mutation", seq=6),
    ]

    assert "open workspace mutations after event stream: ['call-1']" in check_event_invariants(events)


def test_event_invariants_catch_workspace_mutation_completion_without_start() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_mutation_complete", seq=1),
        Event(type="workspace.mutation.completed", run_id="run_bad_mutation_complete", seq=2, data={"tool_call_id": "call-1"}),
        Event(type="artifact.finalization.started", run_id="run_bad_mutation_complete", seq=3),
        Event(type="artifact.finalization.completed", run_id="run_bad_mutation_complete", seq=4),
        Event(type="run.completed", run_id="run_bad_mutation_complete", seq=5),
    ]

    assert "workspace mutation completed without start: call-1" in check_event_invariants(events)


def test_event_invariants_catch_blocked_terminal_without_blocked_event() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_blocked_terminal", seq=1),
        Event(type="model.call.started", run_id="run_bad_blocked_terminal", seq=2, data={"model_call_id": "model-call-1"}),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_bad_blocked_terminal",
            seq=3,
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell", "args": {"cmd": "true"}},
        ),
        Event(type="model.call.completed", run_id="run_bad_blocked_terminal", seq=4, data={"model_call_id": "model-call-1"}),
        Event(type="policy.evaluated", run_id="run_bad_blocked_terminal", seq=5, data={"tool_call_id": "call-1"}),
        Event(
            type="tool.execution.failed",
            run_id="run_bad_blocked_terminal",
            seq=6,
            data={"tool_call_id": "call-1", "tool": "shell", "ok": False, "blocked": True},
        ),
        Event(type="artifact.finalization.started", run_id="run_bad_blocked_terminal", seq=7),
        Event(type="artifact.finalization.completed", run_id="run_bad_blocked_terminal", seq=8),
        Event(type="run.completed", run_id="run_bad_blocked_terminal", seq=9),
    ]

    assert "tool execution terminal marked blocked without blocked event: call-1" in check_event_invariants(events)


def test_event_invariants_catch_missing_terminal_and_finalization() -> None:
    events = [Event(type="run.started", run_id="run_truncated", seq=1)]

    assert "terminal run event is missing" in check_event_invariants(events)


def test_event_invariants_catch_missing_artifact_finalization() -> None:
    events = [
        Event(type="run.started", run_id="run_no_finalization", seq=1),
        Event(type="run.completed", run_id="run_no_finalization", seq=2),
    ]

    assert "artifact finalization is missing" in check_event_invariants(events)


def test_event_invariants_catch_forged_approval_grant() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_approval", seq=1),
        Event(
            type="approval.resolved",
            run_id="run_bad_approval",
            seq=2,
            data={"approval_id": "approval-2", "decision": "approved", "scope": "run", "reason": "approval_grant"},
        ),
        Event(type="artifact.finalization.started", run_id="run_bad_approval", seq=3),
        Event(type="artifact.finalization.completed", run_id="run_bad_approval", seq=4),
        Event(type="run.completed", run_id="run_bad_approval", seq=5),
    ]

    assert "approval grant reused before run-scoped approval: approval-2" in check_event_invariants(events)


def test_event_invariants_catch_unsafe_response_artifact_path() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_artifact", seq=1),
        Event(
            type="model.call.completed",
            run_id="run_bad_artifact",
            seq=2,
            data={"model_call_id": "model-call-1", "response_artifact": "/tmp/leak.json"},
        ),
        Event(type="artifact.finalization.started", run_id="run_bad_artifact", seq=3),
        Event(type="artifact.finalization.completed", run_id="run_bad_artifact", seq=4),
        Event(type="run.completed", run_id="run_bad_artifact", seq=5),
    ]

    assert "artifact path escapes run output: /tmp/leak.json" in check_event_invariants(events)
