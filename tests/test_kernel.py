from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from agentd.contracts import Tool
from agentd.events import EVENT_TYPES, load_events_jsonl
from agentd.kernel import Kernel
from agentd.state import Message, ModelResponse, PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult


class AllowAllPolicy:
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        return PolicyDecision.allow(f"{call.name} allowed")


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

    def compact(self, state: RunState) -> RunState:
        return state


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
