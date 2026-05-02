"""Runtime interfaces for models, profiles, tools, policy, and executors."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from agentd.state import Message, ModelResponse, PolicyDecision, RunState, ToolCall, ToolResult


class Tool(Protocol):
    name: str
    schema: Mapping[str, Any]

    def run(self, call: ToolCall, state: RunState) -> ToolResult: ...


class ModelProvider(Protocol):
    name: str

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse: ...


class Profile(Protocol):
    name: str

    def system_prompt(self) -> str: ...

    def build_messages(self, state: RunState) -> Sequence[Message]: ...

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]: ...

    def should_continue(self, state: RunState) -> bool: ...

    def should_finish(self, state: RunState) -> bool: ...

    def compact(self, state: RunState) -> None: ...


class PolicyEngine(Protocol):
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision: ...


class Executor(Protocol):
    def run_tool(self, tool: Tool, call: ToolCall, state: RunState) -> ToolResult: ...


class LocalExecutor:
    def run_tool(self, tool: Tool, call: ToolCall, state: RunState) -> ToolResult:
        return tool.run(call, state)
