from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentd.contracts import Tool
from agentd.events import DURABLE_EVENT_TYPES, EVENT_TYPES, LIVE_ONLY_EVENT_TYPES, Event, MemoryEventSink, load_events_jsonl
from agentd.kernel import Kernel
from agentd.model_stream import ModelDelta
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


class StreamingModel:
    name = "streaming-model"

    def __init__(self, responses: list[list[ModelDelta]]) -> None:
        self.responses = responses
        self.stream_calls = 0
        self.complete_calls = 0

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        del messages, tools, state
        self.complete_calls += 1
        raise AssertionError("streaming test should not call complete")

    def stream(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState):
        del messages, tools, state
        self.stream_calls += 1
        if not self.responses:
            return
        yield from self.responses.pop(0)


class EventsFileCheckingModel:
    name = "events-file-checking-model"

    def __init__(self) -> None:
        self.saw_incremental_events = False

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        events_path = state.output_dir / "events.jsonl"
        text = events_path.read_text()
        self.saw_incremental_events = all(event_type in text for event_type in ["run.started", "context.built", "model.request.started"])
        return ModelResponse(content="done", finish_reason="stop")


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
        return ToolResult(tool_name=self.name, output="abcdef", data={"output_artifact": "artifacts/tool.txt"})


class LargeDataTool:
    name = "large_data"
    schema = {"name": "large_data"}

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        return ToolResult(tool_name=self.name, output="ok", data={"payload": "x" * 10_000})


def event_types(state: RunState) -> list[str]:
    return [event.type for event in state.events]


def test_kernel_dispatches_model_policy_tool_then_finishes_from_content(tmp_path) -> None:
    noop_call = ToolCall(name="noop")
    model = StaticModel(
        [
            ModelResponse(tool_calls=[noop_call]),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
    )

    state = kernel.run("run a tool then answer", workspace=tmp_path)

    assert state.done is True
    assert state.failed is False
    assert state.final_output == "done"
    assert state.turn_count == 2
    assert state.tool_call_count == 1
    assert [result.tool_name for result in state.tool_results] == ["noop"]
    assert state.tool_results[0].call_id == noop_call.id
    assert event_types(state) == [
        "run.started",
        "context.built",
        "artifact.created",
        "artifact.created",
        "model.request.started",
        "artifact.created",
        "model.completed",
        "tool.call.started",
        "tool.args.completed",
        "tool.policy.evaluated",
        "tool.execution.started",
        "tool.execution.completed",
        "context.built",
        "artifact.created",
        "artifact.created",
        "model.request.started",
        "artifact.created",
        "model.completed",
        "message.completed",
        "diff.finalized",
        "run.completed",
    ]
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "final.md").read_text() == "# Final output\n\ndone\n"
    metrics = json.loads((state.output_dir / "metrics.json").read_text())
    assert metrics["status"] == "completed"
    assert metrics["turn_count"] == 2

    model_request = [event for event in state.events if event.type == "model.request.started"][0]
    model_response = [event for event in state.events if event.type == "model.completed"][0]
    assert model_request.data["context_artifact"] == "artifacts/context-0001.md"
    assert model_request.data["logical_request_artifact"] == "artifacts/model-request-logical-0001.json"
    assert model_request.data["http_request_artifact"] is None
    assert model_response.data["response_artifact"] == "artifacts/model-response-0001.json"

    context = (state.output_dir / model_request.data["context_artifact"]).read_text()
    request = json.loads((state.output_dir / model_request.data["logical_request_artifact"]).read_text())
    response = json.loads((state.output_dir / model_response.data["response_artifact"]).read_text())

    assert "run a tool then answer" in context
    assert "noop" in context
    assert request["provider"] == "static-model"
    assert request["messages"][1] == {"role": "user", "content": "run a tool then answer"}
    assert response["tool_calls"] == [{"id": noop_call.id, "name": "noop", "args": {}}]
    tool_finished = next(event for event in state.events if event.type == "tool.execution.completed")
    assert tool_finished.data == {
        "tool_call_id": noop_call.id,
        "tool": "noop",
        "ok": True,
        "blocked": False,
        "output": "ok",
        "output_chars": 2,
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
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
        budgets=RunBudgets(max_turns=0),
    )

    state = kernel.run("budget failure", workspace=tmp_path)

    assert model.calls == 0
    assert state.done is True
    assert state.failed is True
    assert state.failure_reason == "Run exceeded max_turns budget."
    assert event_types(state) == ["run.started", "diff.finalized", "run.failed"]
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "final.md").read_text() == "# Final output\n\nNo final output produced.\n"
    assert (state.output_dir / "metrics.json").exists()
    assert (state.output_dir / "final.diff").read_text() == ""


def test_events_are_persisted_before_run_finishes(tmp_path) -> None:
    model = EventsFileCheckingModel()
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
    )

    state = kernel.run("check incremental events", workspace=tmp_path)

    assert state.failed is False
    assert model.saw_incremental_events is True


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
    assert event_types(state)[-1] == "run.failed"
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
    assert "tool.execution.started" not in event_types(state)
    tool_finished = next(event for event in state.events if event.type == "tool.execution.failed")
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
    assert event_types(state)[-3:] == ["tool.execution.failed", "diff.finalized", "run.failed"]
    policy_decision = next(event for event in state.events if event.type == "tool.policy.evaluated")
    assert policy_decision.data["allowed"] is False
    assert policy_decision.data["reason"] == "Policy engine error: policy broke"
    tool_finished = next(event for event in state.events if event.type == "tool.execution.failed")
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
    tool_finished = next(event for event in state.events if event.type == "tool.execution.failed")
    assert tool_finished.data["tool_call_id"] == call.id
    assert tool_finished.data["ok"] is False
    assert tool_finished.data["output"] == "Tool error: boom"
    assert tool_finished.data["output_chars"] == len("Tool error: boom")
    assert tool_finished.data["output_truncated"] is False
    assert tool_finished.data["data"] == {"error_type": "RuntimeError"}


def test_unknown_tool_records_result_with_available_tools_and_can_recover(tmp_path) -> None:
    call = ToolCall(name="missing")
    second_call = ToolCall(name="noop")
    model = StaticModel(
        [
            ModelResponse(tool_calls=[call]),
            ModelResponse(tool_calls=[second_call]),
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
    first_finished = [event for event in state.events if event.type == "tool.execution.failed"][0]
    assert first_finished.data["tool_call_id"] == call.id
    assert first_finished.data["ok"] is False
    assert first_finished.data["output"] == "Unknown tool requested: missing"
    assert first_finished.data["data"] == {"error_type": "UnknownTool", "available_tools": ["noop"]}


def test_unknown_tool_is_rejected_before_policy(tmp_path) -> None:
    call = ToolCall(name="missing")
    model = StaticModel([ModelResponse(tool_calls=[call])])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=ExplodingPolicy(),
        budgets=RunBudgets(max_turns=1),
    )

    state = kernel.run("missing tool", workspace=tmp_path)

    assert state.failure_reason == "Run exceeded max_turns budget."
    assert "tool.policy.evaluated" not in event_types(state)
    assert state.tool_results[0].data["error_type"] == "UnknownTool"


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

    tool_finished = next(event for event in state.events if event.type == "tool.execution.completed")
    assert tool_finished.data["output"] == "abc"
    assert tool_finished.data["output_chars"] == 6
    assert tool_finished.data["output_truncated"] is True
    assert tool_finished.data["data"] == {"output_artifact": "artifacts/tool.txt"}


def test_tool_finished_large_data_is_summarized(tmp_path) -> None:
    call = ToolCall(name="large_data")
    model = StaticModel([ModelResponse(tool_calls=[call])])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[LargeDataTool()],
        policy=AllowAllPolicy(),
        budgets=RunBudgets(max_turns=1),
    )

    state = kernel.run("large data", workspace=tmp_path)

    tool_finished = next(event for event in state.events if event.type == "tool.execution.completed")
    assert tool_finished.data["data"]["_truncated"] is True
    assert tool_finished.data["data"]["json_chars"] > 4_000
    assert len(tool_finished.data["data"]["preview"]) == 4_000


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
    assert state.final_output == "final answer"
    assert event_types(state)[-3:] == ["message.completed", "diff.finalized", "run.completed"]


def test_streaming_text_is_live_but_final_response_path_is_shared(tmp_path) -> None:
    sink = MemoryEventSink()
    model = StreamingModel(
        [
            [
                ModelDelta(kind="text_delta", delta="hello "),
                ModelDelta(kind="text_delta", delta="world"),
                ModelDelta(kind="completed", data={"finish_reason": "stop"}),
            ]
        ]
    )
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
        stream=True,
        event_sink=sink,
    )

    state = kernel.run("stream an answer", workspace=tmp_path)

    assert state.failed is False
    assert state.final_output == "hello world"
    assert model.stream_calls == 1
    assert model.complete_calls == 0
    assert "model.stream.started" in event_types(state)
    assert "model.completed" in event_types(state)
    assert "model.text.delta" not in event_types(state)
    assert [event.data["delta"] for event in sink.events if event.type == "model.text.delta"] == ["hello ", "world"]
    model_response = next(event for event in state.events if event.type == "model.completed")
    response = json.loads((state.output_dir / model_response.data["response_artifact"]).read_text())
    assert response["content"] == "hello world"
    assert response["raw"] == {"streamed": True}


def test_streaming_tool_arguments_are_buffered_before_tool_execution(tmp_path) -> None:
    sink = MemoryEventSink()
    model = StreamingModel(
        [
            [
                ModelDelta(
                    kind="tool_call_started",
                    tool_call_id="call_1",
                    data={"id": "call_1", "index": 0, "name": "noop"},
                ),
                ModelDelta(kind="tool_call_args_delta", tool_call_id="call_1", delta="{", data={"index": 0}),
                ModelDelta(kind="tool_call_args_delta", tool_call_id="call_1", delta="}", data={"index": 0}),
                ModelDelta(kind="tool_call_completed", tool_call_id="call_1", data={"index": 0}),
                ModelDelta(kind="completed", data={"finish_reason": "tool_calls"}),
            ],
            [
                ModelDelta(kind="text_delta", delta="done"),
                ModelDelta(kind="completed", data={"finish_reason": "stop"}),
            ],
        ]
    )
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
        stream=True,
        event_sink=sink,
    )

    state = kernel.run("stream a tool call then finish", workspace=tmp_path)

    assert state.failed is False
    assert state.turn_count == 2
    assert state.tool_results == [ToolResult(tool_name="noop", output="ok", call_id="call_1")]
    assert [event.type for event in state.events if event.type.startswith("tool.")] == [
        "tool.call.started",
        "tool.args.completed",
        "tool.policy.evaluated",
        "tool.execution.started",
        "tool.execution.completed",
    ]
    assert [event.data["delta"] for event in sink.events if event.type == "tool.args.delta"] == ["{", "}"]
    tool_requested = next(event for event in state.events if event.type == "tool.args.completed")
    assert tool_requested.data["tool_call_id"] == "call_1"
    assert tool_requested.data["args_preview"] == {}


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
    assert event_types(state)[-1] == "run.failed"


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
        "run.started",
        "run.completed",
        "run.failed",
        "context.built",
        "model.request.started",
        "model.completed",
        "compaction.started",
        "checkpoint.completed",
        "tool.args.completed",
        "tool.policy.evaluated",
        "tool.execution.started",
        "tool.execution.completed",
        "tool.execution.failed",
        "shell.preflight.completed",
        "files.listed",
        "command.started",
        "command.completed",
        "patch.applied",
        "file.read",
        "search.completed",
        "diff.finalized",
        "artifact.created",
        "model.stream.started",
        "model.failed",
        "model.usage",
        "message.completed",
        "tool.call.started",
    } <= EVENT_TYPES


def test_unknown_event_type_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown event type"):
        Event(run_id="run_test", type="TypoEvent")


def test_live_only_protocol_events_are_not_durable_events() -> None:
    assert LIVE_ONLY_EVENT_TYPES.isdisjoint(DURABLE_EVENT_TYPES)
    assert LIVE_ONLY_EVENT_TYPES <= EVENT_TYPES
    with pytest.raises(ValueError, match="Live-only event cannot be durable"):
        Event(run_id="run_test", type="model.text.delta")
    event = Event(run_id="run_test", type="model.text.delta", durability="ephemeral")
    assert event.type == "model.text.delta"


def test_run_state_emit_uses_one_sequence_for_durable_and_live_events(tmp_path) -> None:
    sink = MemoryEventSink()
    state = RunState.create("emit", Workspace(tmp_path))
    state.stream_sink = sink

    started = state.emit("run.started", {"task": "emit"})
    delta = state.emit("model.text.delta", {"delta": "hi"}, visibility="user", durability="ephemeral")
    artifact = state.emit("artifact.created", {"path": "artifacts/a.txt", "kind": "test"})

    assert [started.seq, delta.seq, artifact.seq] == [1, 2, 3]
    assert [event.seq for event in state.events] == [1, 3]
    assert [event.seq for event in sink.events] == [1, 2, 3]
    persisted = load_events_jsonl(state.output_dir / "events.jsonl")
    assert [event.seq for event in persisted] == [1, 3]


def test_event_data_is_json_safe_for_common_non_json_types(tmp_path) -> None:
    class Custom:
        def __repr__(self) -> str:
            return "<Custom value>"

    event = Event(
        run_id="run_test",
        type="artifact.created",
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
