"""Optional working todo extension."""

from __future__ import annotations

from collections.abc import Sequence

from tinyagent.core.context_sources.types import ContextSource
from tinyagent.core.contracts import Tool
from tinyagent.extensions.todo_memory.context import WorkingMemorySource
from tinyagent.extensions.todo_memory.store import TodoStore
from tinyagent.extensions.todo_memory.tools import TodoReadTool, TodoWriteTool


class TodoMemoryExtension:
    name = "todo_memory"

    def __init__(self, store: TodoStore | None = None) -> None:
        self.store = store or TodoStore()

    def tools(self) -> Sequence[Tool]:
        return [TodoReadTool(self.store), TodoWriteTool(self.store)]

    def context_sources(self) -> Sequence[ContextSource]:
        return [WorkingMemorySource(self.store)]
