"""Lifecycle hook invocation with trace events."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from tinyagent.core.contracts import Tool
from tinyagent.core.context import BuiltContext
from tinyagent.core.hooks import TinyHook
from tinyagent.core.state import FinishDecision, ModelResponse, PolicyDecision, RunState, ToolCall, ToolResult

HookErrorPolicy = Literal["fail", "record"]


class HookRunner:
    def __init__(self, hooks: Sequence[TinyHook], *, error_policy: HookErrorPolicy = "fail") -> None:
        self.hooks = tuple(hooks)
        self.error_policy = error_policy

    def call_void(self, state: RunState, method_name: str, *args: Any) -> None:
        for hook, method, name in self._methods(method_name):
            state.emit("hook.started", {"hook": name, "method": method_name})
            try:
                method(*args)
            except Exception as exc:
                self._fail(state, name, method_name, exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": method_name})

    def on_context(self, state: RunState, built_context: BuiltContext) -> BuiltContext:
        return self.transform(state, "on_context", built_context, state)

    def after_model_response(self, state: RunState, response: ModelResponse) -> ModelResponse:
        return self.transform(state, "after_model_response", response, state)

    def after_tool_result(self, state: RunState, result: ToolResult) -> ToolResult:
        return self.transform(state, "after_tool_result", result, state)

    def before_finish(self, state: RunState, response: ModelResponse, decision: FinishDecision) -> FinishDecision:
        return self.transform(state, "before_finish", decision, state, response)

    def transform(self, state: RunState, method_name: str, value: Any, *leading_args: Any) -> Any:
        current = value
        for hook, method, name in self._methods(method_name):
            state.emit("hook.started", {"hook": name, "method": method_name})
            try:
                current = method(*leading_args, current)
            except Exception as exc:
                self._fail(state, name, method_name, exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": method_name})
        return current

    def before_model_call(self, state: RunState, messages: list, tools: list[Tool]) -> tuple[list, list[Tool]]:
        current_messages = messages
        current_tools = tools
        for hook, method, name in self._methods("before_model_call"):
            state.emit("hook.started", {"hook": name, "method": "before_model_call"})
            try:
                returned = method(state, current_messages, current_tools)
                if isinstance(returned, tuple) and len(returned) == 2:
                    current_messages = list(returned[0])
                    current_tools = list(returned[1])
            except Exception as exc:
                self._fail(state, name, "before_model_call", exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": "before_model_call"})
        return current_messages, current_tools

    def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolCall | ToolResult | None:
        current = call
        changed = False
        for hook, method, name in self._methods("before_tool_call"):
            state.emit("hook.started", {"hook": name, "method": "before_tool_call"})
            try:
                returned = method(state, current, decision)
            except Exception as exc:
                self._fail(state, name, "before_tool_call", exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": "before_tool_call"})
                if isinstance(returned, ToolResult):
                    return returned
                if isinstance(returned, ToolCall):
                    current = returned
                    changed = current != call
        return current if changed else None

    def _methods(self, method_name: str):
        for hook in self.hooks:
            method = getattr(hook, method_name, None)
            if not callable(method):
                continue
            yield hook, method, _hook_name(hook)

    def _fail(self, state: RunState, hook_name: str, method_name: str, exc: Exception) -> None:
        state.emit("hook.failed", {"hook": hook_name, "method": method_name, "reason": str(exc)}, visibility="user")
        if self.error_policy == "record":
            return
        reason = f"hook {hook_name}.{method_name} failed: {exc}"
        state.fail(reason)
        raise RuntimeError(reason) from exc


def _hook_name(hook: TinyHook) -> str:
    return str(getattr(hook, "name", hook.__class__.__name__))
