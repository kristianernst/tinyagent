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


def test_event_invariants_for_successful_shell(tmp_path) -> None:
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


def test_event_invariants_allow_run_scoped_approval_grant_reuse() -> None:
    events = [
        Event(type="run.started", run_id="run_approval", seq=1),
        Event(type="approval.requested", run_id="run_approval", seq=2, data={"approval_id": "approval-1"}),
        Event(type="approval.resolved", run_id="run_approval", seq=3, data={"approval_id": "approval-1", "decision": "approved", "scope": "run"}),
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


def test_event_invariants_catch_result_without_model_tool_call() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_result", seq=1),
        Event(type="tool.execution.completed", run_id="run_bad_result", seq=2, data={"tool_call_id": "call-1", "tool": "shell", "ok": True}),
        Event(type="artifact.finalization.started", run_id="run_bad_result", seq=3),
        Event(type="artifact.finalization.completed", run_id="run_bad_result", seq=4),
        Event(type="run.completed", run_id="run_bad_result", seq=5),
    ]

    failures = check_event_invariants(events)

    assert "tool execution terminal without model tool assembly: call-1" in failures
    assert "tool execution terminal without start: call-1" in failures


def test_event_invariants_catch_workspace_delta_completion_without_start() -> None:
    events = [
        Event(type="run.started", run_id="run_bad_delta", seq=1),
        Event(type="workspace.delta.completed", run_id="run_bad_delta", seq=2, data={"tool_call_id": "call-1"}),
        Event(type="artifact.finalization.started", run_id="run_bad_delta", seq=3),
        Event(type="artifact.finalization.completed", run_id="run_bad_delta", seq=4),
        Event(type="run.completed", run_id="run_bad_delta", seq=5),
    ]

    assert "workspace delta completed without start: call-1" in check_event_invariants(events)


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
        Event(type="model.call.completed", run_id="run_bad_artifact", seq=2, data={"model_call_id": "model-call-1", "response_artifact": "/tmp/leak.json"}),
        Event(type="artifact.finalization.started", run_id="run_bad_artifact", seq=3),
        Event(type="artifact.finalization.completed", run_id="run_bad_artifact", seq=4),
        Event(type="run.completed", run_id="run_bad_artifact", seq=5),
    ]

    assert "artifact path escapes run output: /tmp/leak.json" in check_event_invariants(events)
