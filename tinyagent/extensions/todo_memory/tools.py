"""Working todo model tools."""

from __future__ import annotations

from tinyagent.core.contracts import ToolRuntime
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.tools.core import visible_output
from tinyagent.extensions.todo_memory.store import TODO_MD, TodoStore, render_todo_markdown


class TodoReadTool:
    name = "todo_read"
    runtime = ToolRuntime(parallel_safe=True, lock_key="todo_memory")
    schema = {
        "name": "todo_read",
        "description": "Read the current run-scoped working todo list.",
        "parameters": {"type": "object", "properties": {}},
    }

    def __init__(self, store: TodoStore | None = None) -> None:
        self.store = store or TodoStore()

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        todo = self.store.read(state)
        output = render_todo_markdown(todo)
        _emit_todo_event(state, "memory.todo.read", todo)
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(output, state),
            data=_todo_data(todo),
            summary=f"Read {len(todo.items)} todo item(s).",
        )


class TodoWriteTool:
    name = "todo_write"
    runtime = ToolRuntime(lock_key="todo_memory")
    schema = {
        "name": "todo_write",
        "description": "Replace the current run-scoped working todo list.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "text": {"type": "string"},
                            "status": {"type": "string", "enum": ["open", "done"]},
                        },
                        "required": ["text"],
                    },
                },
                "notes": {"type": "string"},
            },
            "required": ["items"],
        },
    }

    def __init__(self, store: TodoStore | None = None) -> None:
        self.store = store or TodoStore()

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        raw_items = call.args.get("items") or []
        if not isinstance(raw_items, list) or not all(isinstance(item, dict) for item in raw_items):
            return ToolResult(tool_name=self.name, call_id=call.id, output="items must be a list of objects", ok=False)
        todo = self.store.write(state, raw_items, notes=str(call.args.get("notes") or ""))
        _emit_todo_event(state, "memory.todo.updated", todo)
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(render_todo_markdown(todo), state),
            data={**_todo_data(todo), "path": TODO_MD.as_posix()},
            summary=f"Wrote {len(todo.items)} todo item(s).",
        )


def _todo_data(todo) -> dict[str, object]:
    return {**_todo_counts(todo), "items": [item.to_json_dict() for item in todo.items]}


def _todo_counts(todo) -> dict[str, object]:
    done = sum(1 for item in todo.items if item.status == "done")
    open_count = len(todo.items) - done
    return {
        "scope": "run",
        "item_count": len(todo.items),
        "open_count": open_count,
        "done_count": done,
    }


def _emit_todo_event(state: RunState, name: str, todo) -> None:
    state.emit("extension.event", {"extension": "todo_memory", "name": name, **_todo_counts(todo), "path": TODO_MD.as_posix()})
