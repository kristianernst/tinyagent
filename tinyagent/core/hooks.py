"""Typed synchronous hook ABI for tinyagent lifecycle extension."""

from __future__ import annotations

from typing import Protocol

from tinyagent.core.context import BuiltContext
from tinyagent.core.state import FinishDecision, ModelResponse, PolicyDecision, RunState, ToolCall, ToolResult


class TinyHook(Protocol):
    name: str

    def on_run_start(self, state: RunState) -> None: ...

    def on_context(self, state: RunState, context: BuiltContext) -> BuiltContext: ...

    def before_model_call(self, state: RunState, messages, tools) -> tuple[object, object]: ...

    def after_model_response(self, state: RunState, response: ModelResponse) -> ModelResponse: ...

    def before_tool_call(
        self,
        state: RunState,
        call: ToolCall,
        decision: PolicyDecision,
    ) -> ToolCall | ToolResult | None: ...

    def after_tool_result(self, state: RunState, result: ToolResult) -> ToolResult: ...

    def before_compact(self, state: RunState) -> None: ...

    def before_finish(self, state: RunState, response: ModelResponse, decision: FinishDecision) -> FinishDecision: ...


class NoopHook:
    name = "noop"

    def on_run_start(self, state: RunState) -> None:
        return None

    def on_context(self, state: RunState, context: BuiltContext) -> BuiltContext:
        return context

    def before_model_call(self, state: RunState, messages, tools) -> tuple[object, object]:
        return messages, tools

    def after_model_response(self, state: RunState, response: ModelResponse) -> ModelResponse:
        return response

    def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolCall | ToolResult | None:
        return None

    def after_tool_result(self, state: RunState, result: ToolResult) -> ToolResult:
        return result

    def before_compact(self, state: RunState) -> None:
        return None

    def before_finish(self, state: RunState, response: ModelResponse, decision: FinishDecision) -> FinishDecision:
        return decision
