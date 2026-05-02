from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest

from agentd.contracts import Tool
from agentd.events import (
    DURABLE_EVENT_TYPES,
    EVENT_DEBUG_LEVELS,
    EVENT_TYPES,
    LIVE_ONLY_EVENT_TYPES,
    Event,
    JsonlStreamSink,
    MemoryEventSink,
    debug_level_from_env,
    event_debug_level,
    load_events_jsonl,
)
from agentd.kernel import Kernel
from agentd.model_stream import ModelDelta
from agentd.replay import render_timeline
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


class ApprovalPolicy:
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        from agentd.state import ApprovalRequest

        return PolicyDecision.needs_approval(
            f"{call.name} requires approval",
            ApprovalRequest(
                approval_id=f"approval_{call.id}",
                run_id=state.run_id,
                turn_id=state.current_turn_id,
                step_id=state.current_step_id,
                action_kind="unknown",
                tool_name=call.name,
                cwd=str(state.workspace.root),
                args_preview=str(call.args),
                command=None,
                risk="low",
            ),
        )


class RunScopeApprovalHandler:
    def __init__(self) -> None:
        self.count = 0

    def resolve(self, request, state):
        from agentd.state import ApprovalResolution

        del state
        self.count += 1
        return ApprovalResolution(request.approval_id, "approved", scope="run", reason="test_run_scope")


class CancellingApprovalHandler:
    def resolve(self, request, state):
        del request
        state.request_cancel("approval cancelled")
        state.raise_if_cancelled()
        raise AssertionError("unreachable")


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
        self.saw_incremental_events = all(event_type in text for event_type in ["run.started", "context.built", "model.call.started"])
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


class CancellingTool:
    name = "cancel"
    schema = {"name": "cancel"}

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        state.request_cancel("test cancellation")
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output="cancelled",
            ok=False,
            data={"cancelled": True, "reason": "test cancellation"},
        )


class LargeDataTool:
    name = "large_data"
    schema = {"name": "large_data"}

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        return ToolResult(tool_name=self.name, output="ok", data={"payload": "x" * 10_000})


class CancellingStreamingModel:
    name = "cancelling-streaming-model"

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        del messages, tools, state
        raise AssertionError("streaming cancellation test should not call complete")

    def stream(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState):
        del messages, tools
        yield ModelDelta(kind="text_delta", delta="partial")
        state.request_cancel("model cancelled")
        yield ModelDelta(kind="text_delta", delta="ignored")


class TimeoutModel:
    name = "timeout-model"

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        del messages, tools, state
        raise TimeoutError("request timeout")


def event_types(state: RunState) -> list[str]:
    return [event.type for event in state.events]


def assert_subsequence(types: list[str], expected: list[str]) -> None:
    cursor = 0
    for event_type in types:
        if cursor < len(expected) and event_type == expected[cursor]:
            cursor += 1
    assert cursor == len(expected), f"missing ordered subsequence: {expected} in {types}"


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
    assert state.turn_count == 1
    assert state.model_call_count == 2
    assert state.tool_call_count == 1
    assert [result.tool_name for result in state.tool_results] == ["noop"]
    assert state.tool_results[0].call_id == noop_call.id
    types = event_types(state)
    assert_subsequence(types, [
        "run.started",
        "workspace.opened",
        "workspace.boundary",
        "turn.started",
        "context.built",
        "model.call.started",
        "step.started",
        "model.tool_call.assembly.started",
        "model.tool_call.assembly.completed",
        "model.call.completed",
        "step.completed",
        "policy.evaluated",
        "tool.execution.started",
        "tool.execution.completed",
        "step.completed",
        "context.built",
        "model.call.started",
        "model.call.completed",
        "model.message.completed",
        "diff.finalized",
        "turn.completed",
        "run.completed",
    ])
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "final.md").read_text() == "# Final output\n\ndone\n"
    message = next(
        event
        for event in state.events
        if event.type == "model.message.completed" and event.data.get("output_path") == "final.md"
    )
    assert message.data["output_path"] == "final.md"
    assert message.artifact_refs == []
    metrics = json.loads((state.output_dir / "metrics.json").read_text())
    assert metrics["status"] == "completed"
    assert metrics["turn_count"] == 1
    assert metrics["model_call_count"] == 2
    assert metrics["workspace_mode"] == "auto"
    assert metrics["approval_mode"] == "yolo"
    assert metrics["sandbox_enforced"] is False

    model_request = [event for event in state.events if event.type == "model.call.started"][0]
    model_response = [event for event in state.events if event.type == "model.call.completed"][0]
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
    assert_subsequence(
        event_types(state),
        [
            "run.started",
            "workspace.boundary",
            "turn.started",
            "artifact.finalization.started",
            "diff.finalized",
            "turn.failed",
            "run.failed",
        ],
    )
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


def test_approval_mode_never_fails_closed_and_blocks_execution(tmp_path) -> None:
    call = ToolCall(name="noop")
    model = StaticModel([ModelResponse(tool_calls=[call]), ModelResponse(content="done", finish_reason="stop")])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=ApprovalPolicy(),
        approval_mode="never",
    )

    state = kernel.run("approval never", workspace=tmp_path)

    types = event_types(state)
    assert state.failed is False
    assert state.final_output == "done"
    assert "approval.requested" in types
    assert "approval.resolved" in types
    assert "tool.execution.blocked" in types
    assert "tool.execution.started" not in types
    resolution = next(event for event in state.events if event.type == "approval.resolved")
    assert resolution.data["decision"] == "denied"
    assert resolution.data["reason"] == "approval_mode_never"


def test_run_scoped_approval_grant_is_reused(tmp_path) -> None:
    call_1 = ToolCall(name="noop", id="call_same")
    call_2 = ToolCall(name="noop", id="call_same")
    handler = RunScopeApprovalHandler()
    model = StaticModel(
        [
            ModelResponse(tool_calls=[call_1]),
            ModelResponse(tool_calls=[call_2]),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=ApprovalPolicy(),
        approval_handler=handler,
        approval_mode="on-request",
    )

    state = kernel.run("approval grant", workspace=tmp_path)

    assert state.failed is False
    assert handler.count == 1
    assert len([event for event in state.events if event.type == "approval.requested"]) == 1
    assert len([event for event in state.events if event.type == "tool.execution.completed"]) == 2


def test_cancel_during_approval_wait_marks_active_step_only(tmp_path) -> None:
    call = ToolCall(name="noop")
    model = StaticModel([ModelResponse(tool_calls=[call])])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=ApprovalPolicy(),
        approval_handler=CancellingApprovalHandler(),
        approval_mode="on-request",
    )

    state = kernel.run("cancel approval", workspace=tmp_path)

    types = event_types(state)
    assert state.cancelled is True
    assert "approval.requested" in types
    assert "step.cancel.requested" in types
    assert "step.cancelled" in types
    assert "tool.execution.started" not in types
    assert_subsequence(
        types,
        ["approval.requested", "step.started", "step.cancel.requested", "step.cancelled", "turn.interrupted", "run.cancelled"],
    )


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
    assert event_types(state)[-1] == "run.failed"
    policy_decision = next(event for event in state.events if event.type == "policy.evaluated")
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
    assert state.turn_count == 1
    assert state.model_call_count == 2
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
    assert "policy.evaluated" not in event_types(state)
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
    assert_subsequence(event_types(state), ["model.message.completed", "diff.finalized", "turn.completed", "run.completed"])


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
    assert "model.call.started" in event_types(state)
    assert "model.call.completed" in event_types(state)
    assert "model.text.delta" not in event_types(state)
    assert [event.data["delta"] for event in sink.events if event.type == "model.text.delta"] == ["hello ", "world"]
    model_response = next(event for event in state.events if event.type == "model.call.completed")
    response = json.loads((state.output_dir / model_response.data["response_artifact"]).read_text())
    assert response["content"] == "hello world"
    assert response["raw"] == {"streamed": True}


def test_streaming_reasoning_visibility_distinguishes_visible_and_private(tmp_path) -> None:
    sink = MemoryEventSink()
    model = StreamingModel(
        [
            [
                ModelDelta(kind="reasoning_visible_delta", delta="visible thought"),
                ModelDelta(kind="reasoning_summary_delta", delta="safe summary"),
                ModelDelta(
                    kind="reasoning_summary_delta",
                    delta="private chain",
                    data={"provider_field": "reasoning_content", "safe_to_display": False},
                ),
                ModelDelta(kind="reasoning_encrypted", delta="opaque"),
                ModelDelta(kind="text_delta", delta="done"),
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

    state = kernel.run("stream reasoning", workspace=tmp_path)

    assert state.failed is False
    assert state.final_output == "done"
    assert not any(event.type == "model.reasoning.delta" for event in state.events)
    visible = next(event for event in sink.events if event.type == "model.reasoning.delta" and event.visibility == "internal")
    safe_summary = [
        event for event in sink.events if event.type == "model.reasoning.delta" and event.data.get("delta") == "safe summary"
    ][0]
    private_summary = [
        event for event in sink.events if event.type == "model.reasoning.delta" and not event.data.get("delta")
    ][0]
    encrypted = next(event for event in sink.events if event.type == "reasoning.encrypted")
    assert visible.visibility == "internal"
    assert visible.data["delta"] == "visible thought"
    assert safe_summary.visibility == "user"
    assert safe_summary.data["delta"] == "safe summary"
    assert private_summary.visibility == "debug"
    assert private_summary.data == {"chars": 13, "item_id": None, "provider_field": "reasoning_content"}
    assert encrypted.visibility == "internal"


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
                ModelDelta(kind="tool_call_args_delta", tool_call_id="index_0", delta="{", data={"index": 0}),
                ModelDelta(kind="tool_call_args_delta", tool_call_id="index_0", delta="}", data={"index": 0}),
                ModelDelta(kind="tool_call_completed", tool_call_id="index_0", data={"index": 0}),
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
    assert state.turn_count == 1
    assert state.model_call_count == 2
    assert state.tool_results == [ToolResult(tool_name="noop", output="ok", call_id="call_1")]
    tool_events = [
        event.type
        for event in state.events
        if event.type in {"policy.evaluated", "tool.execution.started", "tool.execution.completed"}
    ]
    assert tool_events == [
        "policy.evaluated",
        "tool.execution.started",
        "tool.execution.completed",
    ]
    arg_delta_events = [event for event in sink.events if event.type == "model.tool_call.args.delta"]
    assert [event.data["delta"] for event in arg_delta_events] == ["{", "}"]
    assert [event.data["tool_call_id"] for event in arg_delta_events] == ["call_1", "call_1"]
    assert [event.data["tool"] for event in arg_delta_events] == ["noop", "noop"]
    tool_requested = next(event for event in state.events if event.type == "model.tool_call.assembly.completed")
    assert tool_requested.data["tool_call_id"] == "call_1"
    assert tool_requested.data["args"] == {}


def test_invalid_streamed_tool_arguments_fail_without_tool_execution(tmp_path) -> None:
    model = StreamingModel(
        [
            [
                ModelDelta(
                    kind="tool_call_started",
                    tool_call_id="call_1",
                    data={"id": "call_1", "index": 0, "name": "noop"},
                ),
                ModelDelta(kind="tool_call_args_delta", tool_call_id="call_1", delta="[", data={"index": 0}),
                ModelDelta(kind="tool_call_args_delta", tool_call_id="call_1", delta="]", data={"index": 0}),
                ModelDelta(kind="completed", data={"finish_reason": "tool_calls"}),
            ]
        ]
    )
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
        stream=True,
        event_sink=MemoryEventSink(),
    )

    state = kernel.run("stream invalid tool args", workspace=tmp_path)

    assert state.failed is True
    assert state.failure_reason == "Model provider error: Tool call arguments for noop must be a JSON object."
    assert "model.call.failed" in event_types(state)
    assert "tool.execution.started" not in event_types(state)
    assert event_types(state)[-1] == "run.failed"
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "final.md").exists()
    assert (state.output_dir / "metrics.json").exists()
    assert (state.output_dir / "final.diff").exists()


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


def test_cancelled_tool_preserves_completed_steps_and_finalizes_without_completion(tmp_path) -> None:
    first_call = ToolCall(name="noop")
    cancel_call = ToolCall(name="cancel")
    model = StaticModel([ModelResponse(tool_calls=[first_call, cancel_call])])
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool(), CancellingTool()],
        policy=AllowAllPolicy(),
    )

    state = kernel.run("complete one step then cancel", workspace=tmp_path)

    assert state.cancelled is True
    assert state.failed is False
    assert state.cancel_reason == "test cancellation"
    assert [(step.call.name, step.result.data.get("cancelled")) for step in state.tool_steps] == [
        ("noop", None),
        ("cancel", True),
    ]
    types = event_types(state)
    assert "tool.execution.completed" in types
    assert "tool.execution.cancelled" in types
    cancel_tool_events = [
        event.type
        for event in state.events
        if event.data.get("tool_call_id") == cancel_call.id and event.type.startswith("tool.execution.")
    ]
    assert cancel_tool_events == [
        "tool.execution.started",
        "tool.execution.cancelled",
    ]
    assert "run.completed" not in types
    assert_subsequence(types, ["diff.finalized", "turn.interrupted", "run.cancelled"])
    assert (state.output_dir / "final.md").read_text() == "# Final output\n\nNo final output produced.\n"
    metrics = json.loads((state.output_dir / "metrics.json").read_text())
    assert metrics["status"] == "cancelled"
    assert metrics["cancel_reason"] == "test cancellation"


def test_cancelled_model_stream_keeps_partial_text_live_only(tmp_path) -> None:
    sink = MemoryEventSink()
    kernel = Kernel(
        model=CancellingStreamingModel(),
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
        stream=True,
        event_sink=sink,
    )

    state = kernel.run("cancel during stream", workspace=tmp_path)

    assert state.cancelled is True
    assert state.final_output == ""
    assert [event.data["delta"] for event in sink.events if event.type == "model.text.delta"] == ["partial"]
    types = event_types(state)
    assert "model.cancelled" in types
    assert "model.call.completed" not in types
    assert "model.message.completed" not in types
    assert "run.completed" not in types
    assert_subsequence(types, ["diff.finalized", "turn.interrupted", "run.cancelled"])


def test_model_timeout_is_step_timeout_and_terminal_failure(tmp_path) -> None:
    kernel = Kernel(
        model=TimeoutModel(),
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
    )

    state = kernel.run("timeout", workspace=tmp_path)

    types = event_types(state)
    assert state.failed is True
    assert "model.timeout" in types
    assert "step.timeout" in types
    assert "model.call.completed" not in types
    assert_subsequence(types, ["model.timeout", "step.timeout", "turn.failed", "run.failed"])


def test_stream_idle_timeout_is_step_idle_timeout(tmp_path) -> None:
    model = StreamingModel(
        [
            [
                ModelDelta(kind="failed", data={"reason": "idle timeout waiting for chunk"}),
            ]
        ]
    )
    kernel = Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[NoopTool()],
        policy=AllowAllPolicy(),
        stream=True,
    )

    state = kernel.run("idle timeout", workspace=tmp_path)

    types = event_types(state)
    assert state.failed is True
    assert "model.idle_timeout" in types
    assert "step.idle_timeout" in types
    assert_subsequence(types, ["model.idle_timeout", "step.idle_timeout", "turn.failed", "run.failed"])


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
        "run.cancel.requested",
        "run.cancelled",
        "turn.started",
        "turn.completed",
        "turn.interrupted",
        "step.started",
        "step.completed",
        "step.cancel.requested",
        "step.cancelled",
        "workspace.opened",
        "workspace.boundary",
        "workspace.dirty.detected",
        "context.built",
        "model.call.started",
        "model.call.completed",
        "model.message.completed",
        "model.cancelled",
        "model.timeout",
        "model.idle_timeout",
        "model.tool_call.assembly.started",
        "model.tool_call.assembly.completed",
        "model.tool_call.assembly.failed",
        "compaction.started",
        "checkpoint.completed",
        "policy.evaluated",
        "approval.requested",
        "approval.resolved",
        "tool.execution.started",
        "tool.execution.completed",
        "tool.execution.failed",
        "tool.execution.cancelled",
        "tool.execution.blocked",
        "shell.preflight.completed",
        "files.listed",
        "command.started",
        "command.completed",
        "command.failed",
        "command.timeout",
        "command.cancelled",
        "patch.applied",
        "file.read",
        "search.completed",
        "diff.finalized",
        "artifact.created",
        "artifact.finalization.started",
        "artifact.materialized",
        "artifact.finalization.completed",
        "model.call.failed",
        "model.usage",
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


def test_all_events_have_explicit_debug_levels() -> None:
    assert EVENT_TYPES <= EVENT_DEBUG_LEVELS.keys()


def test_debug_level_from_env_validates_values() -> None:
    assert debug_level_from_env({}) == 0
    assert debug_level_from_env({"TINYAGENT_DEBUG": "3"}) == 3

    with pytest.raises(ValueError, match="integer"):
        debug_level_from_env({"TINYAGENT_DEBUG": "verbose"})

    with pytest.raises(ValueError, match="non-negative"):
        debug_level_from_env({"TINYAGENT_DEBUG": "-1"})


def test_jsonl_stream_sink_filters_events_by_debug_level() -> None:
    output = StringIO()
    sink = JsonlStreamSink(output, debug_level=1)
    events = [
        Event(run_id="run_test", type="run.started", data={"task": "debug"}),
        Event(run_id="run_test", type="model.reasoning.delta", data={"delta": "thought"}, visibility="internal", durability="ephemeral"),
        Event(run_id="run_test", type="model.call.completed", data={"provider": "fake"}),
        Event(run_id="run_test", type="context.built"),
        Event(run_id="run_test", type="model.tool_call.args.delta", data={"delta": "{}"}, durability="ephemeral"),
        Event(run_id="run_test", type="model.reasoning.delta", data={"chars": 3}, durability="ephemeral"),
        Event(run_id="run_test", type="reasoning.encrypted", data={"chars": 8}, durability="ephemeral"),
    ]

    for event in events:
        sink.emit(event)

    streamed = [json.loads(line)["type"] for line in output.getvalue().splitlines()]
    assert streamed == ["run.started", "model.call.completed", "model.reasoning.delta"]
    assert [event_debug_level(event) for event in events] == [0, 4, 1, 2, 2, 1, 4]

    internal_output = StringIO()
    internal_sink = JsonlStreamSink(internal_output, debug_level=4)
    internal_sink.emit(events[1])
    assert json.loads(internal_output.getvalue())["data"]["delta"] == "thought"


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
    replay_lines = render_timeline(persisted).splitlines()[2:]
    assert [line.split()[0] for line in replay_lines] == ["0001", "0003"]


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
