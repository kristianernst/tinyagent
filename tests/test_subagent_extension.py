from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tinyagent.core.contracts import Tool
from tinyagent.core.events import load_events_jsonl
from tinyagent.core.kernel import Kernel
from tinyagent.core.state import (
    Message,
    ModelRequestContext,
    ModelResponse,
    PolicyDecision,
    RunBudgets,
    RunState,
    ToolCall,
    Workspace,
)
from tinyagent.evals.invariants import check_event_invariants
from tinyagent.extensions.subagent import AgentTool, SubagentLimits, subagent_extension


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

    def compact(self, state: RunState) -> None:
        return None


class StaticModel:
    name = "static-model"

    def __init__(self, responses: list[ModelResponse]) -> None:
        self.responses = responses

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> ModelResponse:
        del messages, tools, request
        if not self.responses:
            return ModelResponse(content="no response", finish_reason="stop")
        return self.responses.pop(0)


def _parent_kernel(model: StaticModel, **kernel_kwargs) -> Kernel:
    policy = AllowAllPolicy()
    return Kernel(
        model=model,
        profile=BasicProfile(),
        tools=[],
        policy=policy,
        extensions=(subagent_extension(model=model, policy=policy),),
        **kernel_kwargs,
    )


def _agent_call(task: str, **extra) -> ToolCall:
    return ToolCall(name="agent", args={"task": task, **extra})


def _notes_workspace(tmp_path: Path) -> Path:
    (tmp_path / "notes.txt").write_text("status: todo\n")
    return tmp_path


PATCH = "\n".join(
    [
        "*** Begin Patch",
        "*** Update File: notes.txt",
        "@@",
        "-status: todo",
        "+status: done",
        "*** End Patch",
    ]
)


def test_agent_tool_runs_linked_child_run(tmp_path) -> None:
    _notes_workspace(tmp_path)
    model = StaticModel(
        [
            ModelResponse(tool_calls=[_agent_call("Read notes.txt and report its status line.")]),
            ModelResponse(content="Report: notes.txt says status: todo.", finish_reason="stop"),
            ModelResponse(content="done after delegation", finish_reason="stop"),
        ]
    )

    state = _parent_kernel(model).run("delegate a lookup", workspace=tmp_path)

    assert state.final_output == "done after delegation"
    result = state.tool_results[0]
    assert result.tool_name == "agent"
    assert result.ok is True
    assert "Report:" in result.output
    assert result.data["read_only"] is True
    child_run_id = result.data["child_run_id"]

    types = [event.type for event in state.events]
    assert "child_run.started" in types
    assert "child_run.completed" in types
    started = next(event for event in state.events if event.type == "child_run.started")
    assert started.data["child_run_id"] == child_run_id

    summary_path = state.output_dir / result.data["summary_artifact"]
    assert summary_path.exists()
    assert "Report:" in summary_path.read_text()

    child_events = load_events_jsonl(tmp_path / ".tinyagent" / "runs" / child_run_id / "events.jsonl")
    child_started = next(event for event in child_events if event.type == "run.started")
    assert child_started.data["parent_run_id"] == state.run_id
    assert child_started.data["parent_event_id"] == started.id
    assert child_started.data["profile"] == "tiny-pi"

    check_event_invariants(state.events)


def test_read_only_child_cannot_edit(tmp_path) -> None:
    _notes_workspace(tmp_path)
    model = StaticModel(
        [
            ModelResponse(tool_calls=[_agent_call("Set status to done in notes.txt.")]),
            ModelResponse(tool_calls=[ToolCall(name="apply_patch", args={"patch": PATCH})]),
            ModelResponse(content="Edit was blocked by policy: read-only subagent.", finish_reason="stop"),
            ModelResponse(content="parent done", finish_reason="stop"),
        ]
    )

    state = _parent_kernel(model).run("delegate an edit without permission", workspace=tmp_path)

    assert (tmp_path / "notes.txt").read_text() == "status: todo\n"
    result = state.tool_results[0]
    assert result.ok is True
    assert result.data["read_only"] is True
    assert "blocked" in result.output.lower()


def test_allow_edits_child_mutates_workspace(tmp_path) -> None:
    _notes_workspace(tmp_path)
    model = StaticModel(
        [
            ModelResponse(tool_calls=[_agent_call("Set status to done in notes.txt.", allow_edits=True)]),
            ModelResponse(tool_calls=[ToolCall(name="apply_patch", args={"patch": PATCH})]),
            ModelResponse(content="Updated notes.txt status line.", finish_reason="stop"),
            ModelResponse(content="parent done", finish_reason="stop"),
        ]
    )

    state = _parent_kernel(model).run("delegate an edit", workspace=tmp_path)

    assert (tmp_path / "notes.txt").read_text() == "status: done\n"
    result = state.tool_results[0]
    assert result.ok is True
    assert result.data["read_only"] is False


def test_plan_mode_parent_forces_read_only_child(tmp_path) -> None:
    _notes_workspace(tmp_path)
    model = StaticModel(
        [
            ModelResponse(tool_calls=[_agent_call("Try to set status to done.", allow_edits=True)]),
            ModelResponse(content="Read-only report.", finish_reason="stop"),
            ModelResponse(content="parent done", finish_reason="stop"),
        ]
    )

    state = _parent_kernel(model, session_mode="plan").run("plan-mode delegation", workspace=tmp_path)

    result = state.tool_results[0]
    assert result.ok is True
    assert result.data["read_only"] is True
    child_events = load_events_jsonl(tmp_path / ".tinyagent" / "runs" / result.data["child_run_id"] / "events.jsonl")
    child_started = next(event for event in child_events if event.type == "run.started")
    assert child_started.data["session_mode"] == "plan"
    assert (tmp_path / "notes.txt").read_text() == "status: todo\n"


def test_subagent_depth_guard(tmp_path) -> None:
    tool = AgentTool(lambda name, budgets: (_ for _ in ()).throw(AssertionError("factory must not run")))
    state = RunState.create(
        "child task",
        Workspace(root=tmp_path),
        run_id="run_child",
        output_dir=tmp_path / "out",
        parent_run_id="run_parent",
    )

    result = tool.run(_agent_call("go deeper"), state)

    assert result.ok is False
    assert "cannot spawn" in result.output.lower()


def test_child_budgets_clamped_to_parent_remaining_time(tmp_path) -> None:
    tool = AgentTool(lambda name, budgets: None, limits=SubagentLimits(max_run_seconds=300))
    state = RunState.create(
        "parent task",
        Workspace(root=tmp_path),
        budgets=RunBudgets(max_run_seconds=600),
        run_id="run_parent",
        output_dir=tmp_path / "out",
    )
    state.started_at = datetime.now(UTC) - timedelta(seconds=500)

    budgets = tool._child_budgets(state)

    assert 70 <= budgets.max_run_seconds <= 100
    assert budgets.max_model_calls == SubagentLimits().max_model_calls

    state.started_at = datetime.now(UTC) - timedelta(seconds=10_000)
    assert tool._child_budgets(state).max_run_seconds == 30
