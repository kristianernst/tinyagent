"""Runtime interfaces for models, profiles, tools, policy, and executors."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from tinyagent.core.model_stream import ModelDelta
from tinyagent.core.state import (
    ApprovalRequest,
    ApprovalResolution,
    FinishDecision,
    Message,
    ModelRequestContext,
    ModelResponse,
    PolicyDecision,
    RunState,
    ToolCall,
    ToolResult,
)


@dataclass(frozen=True)
class ToolRuntime:
    parallel_safe: bool = False
    mutates_workspace: bool = False
    requires_shell: bool = False
    requires_network: bool = False
    lock_key: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "parallel_safe": self.parallel_safe,
            "mutates_workspace": self.mutates_workspace,
            "requires_shell": self.requires_shell,
            "requires_network": self.requires_network,
            "lock_key": self.lock_key,
        }


DEFAULT_TOOL_RUNTIME = ToolRuntime()


def tool_runtime(tool: Tool) -> ToolRuntime:
    runtime = getattr(tool, "runtime", None)
    return runtime if isinstance(runtime, ToolRuntime) else DEFAULT_TOOL_RUNTIME


class Tool(Protocol):
    """ToolResult.data is small metadata only; large payloads should be artifacts."""

    name: str
    schema: Mapping[str, Any]
    runtime: ToolRuntime

    def run(self, call: ToolCall, state: RunState) -> ToolResult: ...


class ModelProvider(Protocol):
    name: str

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> ModelResponse: ...


class StreamingModelProvider(ModelProvider, Protocol):
    def stream(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> Iterable[ModelDelta]: ...


@dataclass(frozen=True)
class ProfileRuntimeCapabilities:
    skills: bool = True
    dynamic_context: bool = True
    workspace_index: bool = True
    extensions: bool = True
    contextfs: bool = True
    tool_names: tuple[str, ...] | None = None


class Profile(Protocol):
    name: str

    def system_prompt(self) -> str: ...

    def build_messages(self, state: RunState) -> Sequence[Message]: ...

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]: ...

    def should_continue(self, state: RunState) -> bool: ...

    def should_finish(self, state: RunState) -> bool: ...

    def before_finish(self, state: RunState, response: ModelResponse) -> FinishDecision: ...

    def should_compact(self, state: RunState) -> bool: ...

    def compact(self, state: RunState) -> None: ...


class PolicyEngine(Protocol):
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision: ...


class ApprovalHandler(Protocol):
    def resolve(self, request: ApprovalRequest, state: RunState) -> ApprovalResolution: ...


class Executor(Protocol):
    def run_tool(self, tool: Tool, call: ToolCall, state: RunState) -> ToolResult: ...


class LocalExecutor:
    def run_tool(self, tool: Tool, call: ToolCall, state: RunState) -> ToolResult:
        return tool.run(call, state)
