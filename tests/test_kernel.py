from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentd.contracts import Tool
from agentd.events import EVENT_TYPES, Event, load_events_jsonl
from agentd.kernel import Kernel
from agentd.state import Message, ModelResponse, PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult, Workspace


class AllowAllPolicy:
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        return PolicyDecision.allow(f"{call.name} allowed")


class DenyAllPolicy:
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        return PolicyDecision.deny(f"{call.name} denied")


class ExplodingPolicy:
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        raise RuntimeError("policy broke")


class BasicProfile:
    name = "test-profile"

    def system_prompt(self) -> str:
        return "test system prompt"

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return [
            Message(role="system", content=self.system_prompt()),
            Message(role="user", content=state.task),
        ]

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        return list(all_tools.values())

    def should_continue(self, state: RunState) -> bool:
        return True

    def should_finish(self, state: RunState) -> bool:
        return False

    def compact(self, state: RunState) -> None:
        return None


class StaticModel:
    name = "static-model"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses
        self.calls = 0

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        self.calls += 1
        if not self.responses:
            return ModelResponse(content="no response", finish_reason="stop")
        return self.responses.pop(0)


class FinishTool:
    name = "finish"
    schema = {"name": "finish"}

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        return ToolResult(tool_name=self.name, output=call.args.get("summary", "finished"), finish=True)


class NoopTool:
    name = "noop"
    schema = {"name": "noop"}

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        return ToolResult(tool_name=self.name, output="ok")


class ExplodingTool:
    name = "explode"
    schema = {"name": "explode"}

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        raise RuntimeError("boom")


class LongOutputTool:
    name = "long_output"
    schema = {"name": "long_output"}

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        return ToolResult(tool_name=self.name, output="abcdef", data={"full_output_artifact": "artifacts/tool.txt"})


def event_types(state: RunState) -> list[str]:
    return [event.type for event in state.events]


def test_kernel_dispatches_model_policy_and_tool_until_finish(tmp_path) -> None:
    finish_call = ToolCall(name="finish", args={"summary": "done"})
    model = StaticModel([ModelResponse(tool_calls=[finish_call])])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[FinishTool()],
        policy=AllowAllPolicy(),
    )

    state = kernel.run("finish the task", workspace=tmp_path)

    assert state.done is True
    assert state.failed is False
    assert state.summary == "done"
    assert state.turn_count == 1
    assert state.tool_call_count == 1
    assert [result.tool_name for result in state.tool_results] == ["finish"]
    assert state.tool_results[0].call_id == finish_call.id
    assert event_types(state) == [
        "RunStarted",
        "ContextBuilt",
        "ArtifactWritten",
        "ArtifactWritten",
        "ModelRequest",
        "ArtifactWritten",
        "ModelResponse",
        "ToolCallRequested",
        "PolicyDecision",
        "ToolCallStarted",
        "ToolCallFinished",
        "RunFinished",
    ]
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "summary.md").read_text() == "# Run finished\n\ndone\n"
    metrics = json.loads((state.output_dir / "metrics.json").read_text())
    assert metrics["status"] == "finished"
    assert metrics["turn_count"] == 1

    model_request = next(event for event in state.events if event.type == "ModelRequest")
    model_response = next(event for event in state.events if event.type == "ModelResponse")
    assert model_request.data["context_artifact"] == "artifacts/context-0001.md"
    assert model_request.data["request_artifact"] == "artifacts/model-request-0001.json"
    assert model_response.data["response_artifact"] == "artifacts/model-response-0001.json"

    context = (state.output_dir / model_request.data["context_artifact"]).read_text()
    request = json.loads((state.output_dir / model_request.data["request_artifact"]).read_text())
    response = json.loads((state.output_dir / model_response.data["response_artifact"]).read_text())

    assert "finish the task" in context
    assert "finish" in context
    assert request["provider"] == "static-model"
    assert request["messages"][1] == {"role": "user", "content": "finish the task"}
    assert response["tool_calls"] == [{"id": finish_call.id, "name": "finish", "args": {"summary": "done"}}]
    tool_finished = next(event for event in state.events if event.type == "ToolCallFinished")
    assert tool_finished.data == {
        "tool_call_id": finish_call.id,
        "tool": "finish",
        "ok": True,
        "finish": True,
        "blocked": False,
        "output": "done",
        "output_chars": 4,
        "output_truncated": False,
        "data": {},
    }

    loaded_events = load_events_jsonl(state.output_dir / "events.jsonl")
    assert [event.to_json_dict() for event in loaded_events] == [event.to_json_dict() for event in state.events]


def test_kernel_max_turn_failure_writes_required_outputs(tmp_path) -> None:
    model = StaticModel([ModelResponse(content="should not be called")])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[FinishTool()],
        policy=AllowAllPolicy(),
        budgets=RunBudgets(max_turns=0),
    )

    state = kernel.run("budget failure", workspace=tmp_path)

    assert model.calls == 0
    assert state.done is True
    assert state.failed is True
    assert state.failure_reason == "Run exceeded max_turns budget."
    assert event_types(state) == ["RunStarted", "RunFailed"]
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "summary.md").read_text() == "# Run failed\n\nRun exceeded max_turns budget.\n"
    assert (state.output_dir / "metrics.json").exists()
    assert (state.output_dir / "final.diff").read_text() == ""


def test_kernel_max_tool_call_failure_is_evented(tmp_path) -> None:
    model = StaticModel(
        [
            ModelResponse(
                tool_calls=[
                    ToolCall(name="noop"),
                    ToolCall(name="noop"),
                ]
            )
        ]
    )
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
        budgets=RunBudgets(max_tool_calls=1),
    )

    state = kernel.run("tool budget failure", workspace=tmp_path)

    assert state.done is True
    assert state.failed is True
    assert state.failure_reason == "Run exceeded max_tool_calls budget."
    assert state.turn_count == 1
    assert state.tool_call_count == 1
    assert event_types(state)[-1] == "RunFailed"
    metrics = json.loads((state.output_dir / "metrics.json").read_text())
    assert metrics["status"] == "failed"
    assert metrics["tool_call_count"] == 1


def test_denied_tool_call_gets_finished_event_and_counts_requested_call(tmp_path) -> None:
    denied_call = ToolCall(name="noop")
    model = StaticModel([ModelResponse(tool_calls=[denied_call])])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=DenyAllPolicy(),
        budgets=RunBudgets(max_turns=1),
    )

    state = kernel.run("deny tool", workspace=tmp_path)

    assert state.failed is True
    assert state.failure_reason == "Run exceeded max_turns budget."
    assert state.tool_call_count == 1
    assert state.tool_results == [
        ToolResult(
            tool_name="noop",
            output="noop denied",
            call_id=denied_call.id,
            ok=False,
            data={"blocked": True},
        )
    ]
    assert "ToolCallStarted" not in event_types(state)
    tool_finished = next(event for event in state.events if event.type == "ToolCallFinished")
    assert tool_finished.data["tool_call_id"] == denied_call.id
    assert tool_finished.data["ok"] is False
    assert tool_finished.data["blocked"] is True
    assert tool_finished.data["output"] == "noop denied"
    assert tool_finished.data["output_chars"] == len("noop denied")
    assert tool_finished.data["output_truncated"] is False
    assert tool_finished.data["data"] == {"blocked": True}


def test_policy_exception_fails_closed_and_records_tool_result(tmp_path) -> None:
    call = ToolCall(name="noop")
    model = StaticModel([ModelResponse(tool_calls=[call])])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=ExplodingPolicy(),
    )

    state = kernel.run("policy error", workspace=tmp_path)

    assert state.failed is True
    assert state.failure_reason == "Policy engine error: policy broke"
    assert state.tool_call_count == 1
    assert state.tool_results == [
        ToolResult(
            tool_name="noop",
            output="Policy engine error: policy broke",
            call_id=call.id,
            ok=False,
            data={"blocked": True, "error_type": "RuntimeError"},
        )
    ]
    assert event_types(state)[-3:] == ["PolicyDecision", "ToolCallFinished", "RunFailed"]
    policy_decision = next(event for event in state.events if event.type == "PolicyDecision")
    assert policy_decision.data["allowed"] is False
    assert policy_decision.data["reason"] == "Policy engine error: policy broke"
    tool_finished = next(event for event in state.events if event.type == "ToolCallFinished")
    assert tool_finished.data["blocked"] is True
    assert tool_finished.data["data"] == {"blocked": True, "error_type": "RuntimeError"}


def test_tool_exception_gets_finished_event(tmp_path) -> None:
    call = ToolCall(name="explode")
    model = StaticModel([ModelResponse(tool_calls=[call])])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[ExplodingTool()],
        policy=AllowAllPolicy(),
        budgets=RunBudgets(max_turns=1),
    )

    state = kernel.run("explode", workspace=tmp_path)

    assert state.failed is True
    assert state.failure_reason == "Run exceeded max_turns budget."
    assert state.tool_call_count == 1
    assert state.tool_results[0].call_id == call.id
    assert state.tool_results[0].ok is False
    assert state.tool_results[0].output == "Tool error: boom"
    tool_finished = next(event for event in state.events if event.type == "ToolCallFinished")
    assert tool_finished.data["tool_call_id"] == call.id
    assert tool_finished.data["ok"] is False
    assert tool_finished.data["output"] == "Tool error: boom"
    assert tool_finished.data["output_chars"] == len("Tool error: boom")
    assert tool_finished.data["output_truncated"] is False
    assert tool_finished.data["data"] == {"error_type": "RuntimeError"}


def test_unknown_tool_records_result_with_available_tools_and_can_recover(tmp_path) -> None:
    call = ToolCall(name="missing")
    finish_call = ToolCall(name="noop")
    model = StaticModel(
        [
            ModelResponse(tool_calls=[call]),
            ModelResponse(tool_calls=[finish_call]),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
        budgets=RunBudgets(max_turns=2),
    )

    state = kernel.run("missing tool", workspace=tmp_path)

    assert state.failed is True
    assert state.failure_reason == "Run exceeded max_turns budget."
    assert state.turn_count == 2
    assert state.tool_call_count == 2
    first_finished = [event for event in state.events if event.type == "ToolCallFinished"][0]
    assert first_finished.data["tool_call_id"] == call.id
    assert first_finished.data["ok"] is False
    assert first_finished.data["output"] == "Unknown tool requested: missing"
    assert first_finished.data["data"] == {"error_type": "UnknownTool", "available_tools": ["noop"]}


def test_tool_finished_output_is_truncated(tmp_path) -> None:
    call = ToolCall(name="long_output")
    model = StaticModel([ModelResponse(tool_calls=[call])])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[LongOutputTool()],
        policy=AllowAllPolicy(),
        budgets=RunBudgets(max_turns=1, max_command_output_chars_visible=3),
    )

    state = kernel.run("long output", workspace=tmp_path)

    tool_finished = next(event for event in state.events if event.type == "ToolCallFinished")
    assert tool_finished.data["output"] == "abc"
    assert tool_finished.data["output_chars"] == 6
    assert tool_finished.data["output_truncated"] is True
    assert tool_finished.data["data"] == {"full_output_artifact": "artifacts/tool.txt"}


def test_text_only_model_response_finishes_run(tmp_path) -> None:
    model = StaticModel([ModelResponse(content="final answer", finish_reason="stop")])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
    )

    state = kernel.run("answer", workspace=tmp_path)

    assert state.failed is False
    assert state.summary == "final answer"
    assert event_types(state)[-1] == "RunFinished"


def test_empty_model_response_without_tool_calls_fails(tmp_path) -> None:
    model = StaticModel([ModelResponse()])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
    )

    state = kernel.run("empty", workspace=tmp_path)

    assert state.failed is True
    assert state.failure_reason == "Model returned no content and no tool calls."
    assert event_types(state)[-1] == "RunFailed"


def test_workspace_must_exist(tmp_path) -> None:
    missing = tmp_path / "missing"

    with pytest.raises(ValueError, match="Workspace does not exist"):
        RunState.create("task", Workspace(missing))


def test_workspace_must_be_directory(tmp_path) -> None:
    file_path = tmp_path / "workspace.txt"
    file_path.write_text("not a dir")

    with pytest.raises(ValueError, match="Workspace does not exist"):
        RunState.create("task", Workspace(file_path))


def test_custom_output_dir_is_resolved(tmp_path) -> None:
    output_dir = tmp_path / "workspace" / ".." / "out"
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    state = RunState.create("task", Workspace(workspace), output_dir=output_dir)

    assert state.output_dir == (tmp_path / "out").resolve()


def test_event_taxonomy_includes_milestone_zero_required_events() -> None:
    assert {
        "RunStarted",
        "RunFinished",
        "RunFailed",
        "ContextBuilt",
        "ModelRequest",
        "ModelResponse",
        "ToolCallRequested",
        "PolicyDecision",
        "ToolCallStarted",
        "ToolCallFinished",
        "CommandStarted",
        "CommandFinished",
        "PatchApplied",
        "FileRead",
        "SearchCompleted",
        "DiffSnapshot",
        "ArtifactWritten",
    } <= EVENT_TYPES


def test_unknown_event_type_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown event type"):
        Event(run_id="run_test", type="TypoEvent")


def test_event_data_is_json_safe_for_common_non_json_types(tmp_path) -> None:
    class Custom:
        def __repr__(self) -> str:
            return "<Custom value>"

    event = Event(
        run_id="run_test",
        type="ArtifactWritten",
        data={
            "path": Path("somewhere"),
            "time": datetime(2026, 4, 25, tzinfo=UTC),
            "tuple": ("a", Path("b")),
            "bytes": b"hello",
            "custom": Custom(),
            12: "numeric key",
        },
    )

    assert event.to_json_dict()["data"] == {
        "path": "somewhere",
        "time": "2026-04-25T00:00:00Z",
        "tuple": ["a", "b"],
        "bytes": "hello",
        "custom": "<Custom value>",
        "12": "numeric key",
    }
    (tmp_path / "events.jsonl").write_text(json.dumps(event.to_json_dict()) + "\n")
    assert load_events_jsonl(tmp_path / "events.jsonl")[0].data["custom"] == "<Custom value>"
