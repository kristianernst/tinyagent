from __future__ import annotations

import json

from tinyagent.core.context_sources import ContextReadTool, ContextRegistry, ContextSearchTool
from tinyagent.core.contextfs import refresh_contextfs, resolve_context_path
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import LocalPolicy
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.state import ModelResponse, RunBudgets, RunState, ToolCall, Workspace
from tinyagent.core.tools import default_tools
from tinyagent.extensions.todo_memory import TodoMemoryExtension
from tinyagent.extensions.todo_memory.context import WorkingMemorySource
from tinyagent.extensions.todo_memory.store import MAX_TODO_ITEMS, MAX_TODO_NOTES_CHARS, MAX_TODO_TEXT_CHARS, TODO_MD
from tinyagent.extensions.todo_memory.tools import TodoReadTool, TodoWriteTool
from tinyagent.runtime.server import RunController, RuntimeConfig


def test_todo_read_empty_and_write_list(tmp_path) -> None:
    state = RunState.create("todo", Workspace(tmp_path), run_id="run_todo")

    empty = TodoReadTool().run(ToolCall(name="todo_read"), state)
    written = TodoWriteTool().run(
        ToolCall(
            name="todo_write",
            args={
                "items": [
                    {"text": "Inspect policy", "status": "open"},
                    {"id": "todo_keep", "text": "Add tests", "status": "done"},
                ],
                "notes": "Verify after writing.",
            },
        ),
        state,
    )

    assert empty.ok is True
    assert "No todo items" in empty.output
    assert written.ok is True
    assert "todo_1 Inspect policy" in written.output
    assert "todo_keep Add tests" in written.output
    assert (state.output_dir / "context/memory/todo.json").exists()
    assert (state.output_dir / "context/memory/todo.md").exists()
    refresh_contextfs(state)
    assert resolve_context_path(state, "context/memory/todo.md") == state.output_dir / TODO_MD
    assert "context/memory/todo.md" in (state.output_dir / "context/INDEX.md").read_text()
    assert [event.data["name"] for event in state.events if event.type == "extension.event"] == [
        "memory.todo.read",
        "memory.todo.updated",
    ]


def test_todo_write_preserves_existing_ids_created_at(tmp_path) -> None:
    state = RunState.create("todo", Workspace(tmp_path), run_id="run_todo_preserve")
    writer = TodoWriteTool()

    first = writer.run(ToolCall(name="todo_write", args={"items": [{"id": "todo_a", "text": "First"}]}), state)
    second = writer.run(ToolCall(name="todo_write", args={"items": [{"id": "todo_a", "text": "First", "status": "done"}]}), state)

    assert first.ok is True
    assert second.ok is True
    assert first.data["item_count"] == 1
    assert second.data["done_count"] == 1
    first_item = first.data["items"][0]
    second_item = second.data["items"][0]
    assert first_item["created_at"] == second_item["created_at"]
    assert second_item["updated_at"] >= first_item["updated_at"]


def test_todo_write_bounds_payload_and_generates_unique_ids(tmp_path) -> None:
    state = RunState.create("todo", Workspace(tmp_path), run_id="run_todo_bounds")
    writer = TodoWriteTool()

    result = writer.run(
        ToolCall(
            name="todo_write",
            args={
                "items": [
                    {"text": "generated"},
                    {"id": "todo_1", "text": "explicit", "source": "ignored"},
                    *({"text": "x" * (MAX_TODO_TEXT_CHARS + 20)} for _ in range(MAX_TODO_ITEMS + 10)),
                ],
                "notes": "n" * (MAX_TODO_NOTES_CHARS + 20),
            },
        ),
        state,
    )

    todo = state.output_dir / "context/memory/todo.json"
    saved = json.loads(todo.read_text())
    ids = [item["id"] for item in saved["items"]]
    assert result.ok is True
    assert len(ids) == MAX_TODO_ITEMS
    assert len(ids) == len(set(ids))
    assert result.data["items"][1]["source"] == "model"
    assert len(result.data["items"][-1]["text"]) == MAX_TODO_TEXT_CHARS
    assert len(saved["notes"]) == MAX_TODO_NOTES_CHARS


def test_todo_context_source_search_and_read(tmp_path) -> None:
    state = RunState.create("todo", Workspace(tmp_path), run_id="run_todo_context")
    TodoWriteTool().run(ToolCall(name="todo_write", args={"items": [{"text": "Inspect ContextBuilder"}]}), state)
    state.context_registry = ContextRegistry([WorkingMemorySource()])

    searched = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "ContextBuilder", "source": "memory"}), state)
    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "memory:todo/current"}), state)

    assert searched.ok is True
    assert "memory:todo/current" in searched.output
    assert read.ok is True
    assert "Inspect ContextBuilder" in read.output


def test_todo_policy_allows_run_scoped_memory(tmp_path) -> None:
    state = RunState.create("todo", Workspace(tmp_path), run_id="run_todo_policy")

    read = LocalPolicy().evaluate(ToolCall(name="todo_read"), state)
    write = LocalPolicy().evaluate(ToolCall(name="todo_write", args={"items": []}), state)
    context = LocalPolicy().evaluate(ToolCall(name="context_read", args={"ref": "memory:todo/current"}), state)

    assert read.kind == "allow"
    assert write.kind == "allow"
    assert context.kind == "allow"


def test_todo_extension_visible_only_when_enabled(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        extensions=[TodoMemoryExtension()],
        budgets=RunBudgets(max_turns=1),
    ).run("todo", workspace=tmp_path, run_id="run_todo_kernel")

    context_built = next(event for event in state.events if event.type == "context.built")
    assert "todo_read" in context_built.data["visible_tools"]
    assert "memory" in state.context_registry.sources


def test_runtime_todo_endpoint_reads_run_state(tmp_path) -> None:
    controller = RunController(
        RuntimeConfig(
            workspace=tmp_path,
            run_root=tmp_path / "runs",
            provider_factory=lambda _task: FakeModelProvider([ModelResponse(content="done")]),
            todo_memory_enabled=True,
        )
    )
    run_path = controller.store.run_path("run_todo_endpoint")
    run_path.mkdir(parents=True)
    (run_path / "events.jsonl").write_text("")
    (run_path / "context/memory").mkdir(parents=True)
    (run_path / "context/memory/todo.json").write_text('{"version":1,"items":[],"notes":"hello"}\n')

    assert controller.todo_state("run_todo_endpoint")["notes"] == "hello"


def test_runtime_todo_endpoint_requires_enabled_extension(tmp_path) -> None:
    controller = RunController(
        RuntimeConfig(
            workspace=tmp_path,
            run_root=tmp_path / "runs",
            provider_factory=lambda _task: FakeModelProvider([ModelResponse(content="done")]),
        )
    )
    run_path = controller.store.run_path("run_todo_disabled")
    run_path.mkdir(parents=True)
    (run_path / "events.jsonl").write_text("")

    try:
        controller.todo_state("run_todo_disabled")
    except FileNotFoundError as exc:
        assert "not enabled" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("todo_state should require enabled todo memory extension")
