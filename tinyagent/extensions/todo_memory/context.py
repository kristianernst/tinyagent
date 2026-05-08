"""Working todo context source."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tinyagent.core.context_sources.types import ContextChunk, ContextRef
from tinyagent.core.state import RunState
from tinyagent.extensions.todo_memory.store import TodoStore, render_todo_markdown


class WorkingMemorySource:
    name = "memory"
    description = "Run-scoped working todo memory. Use todo_read/todo_write for multi-step progress; read memory:todo/current for details."
    priority = 0

    def __init__(self, store: TodoStore | None = None) -> None:
        self.store = store or TodoStore()

    def search(
        self,
        query: str,
        *,
        workspace: Path,
        state: RunState,
        kind: str | None = None,
        limit: int = 10,
    ) -> Sequence[ContextRef]:
        del workspace, limit
        if kind not in {None, "todo", "working_memory"}:
            return []
        todo = self.store.read(state)
        haystack = f"{todo.notes} " + " ".join(item.text for item in todo.items)
        if query.lower() not in haystack.lower() and todo.items:
            return []
        if not todo.items and query:
            return []
        return [
            ContextRef(
                ref="memory:todo/current",
                source=self.name,
                title="Working todo",
                kind="working_memory",
                summary=f"{len(todo.items)} item(s), {sum(1 for item in todo.items if item.status == 'open')} open.",
            )
        ]

    def read(
        self,
        ref: str,
        *,
        workspace: Path,
        state: RunState,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> ContextChunk:
        del workspace
        if ref != "todo/current":
            raise KeyError(ref)
        text = render_todo_markdown(self.store.read(state))
        lines = text.splitlines()
        start = max(start_line or 1, 1)
        limit = max(max_lines or 400, 1)
        selected = lines[start - 1 : start - 1 + limit]
        return ContextChunk(
            ref="memory:todo/current",
            source=self.name,
            title="Working todo",
            content="\n".join(selected),
            start_line=start,
            end_line=start + len(selected) - 1 if selected else start - 1,
            total_lines=len(lines),
            truncated=start + len(selected) - 1 < len(lines),
        )
