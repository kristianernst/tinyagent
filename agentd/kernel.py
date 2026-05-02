"""Minimal tinyagent kernel loop."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from agentd.context import BuiltContext, estimate_messages_tokens, estimate_tools_tokens, message_text
from agentd.contracts import Executor, LocalExecutor, ModelProvider, PolicyEngine, Profile, Tool
from agentd.events import json_safe
from agentd.output import (
    capture_final_diff,
    write_model_http_request_artifact,
    write_model_request_artifacts,
    write_model_response_artifact,
    write_run_outputs,
)
from agentd.state import Message, PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult, ToolStep, Workspace
from agentd.tools import shell_preflight

MAX_EVENT_DATA_CHARS = 4_000


class Kernel:
    """Small runtime that owns state, model calls, policy checks, and tool dispatch."""

    def __init__(
        self,
        *,
        model: ModelProvider,
        profile: Profile,
        tools: Iterable[Tool],
        policy: PolicyEngine,
        executor: Executor | None = None,
        budgets: RunBudgets | None = None,
    ) -> None:
        self.model = model
        self.profile = profile
        self.tools = {tool.name: tool for tool in tools}
        self.policy = policy
        self.executor = executor or LocalExecutor()
        self.budgets = budgets or RunBudgets()

    def run(
        self,
        task: str,
        *,
        workspace: Path | str,
        run_id: str | None = None,
        output_dir: Path | None = None,
    ) -> RunState:
        state = RunState.create(
            task,
            Workspace(Path(workspace)),
            budgets=self.budgets,
            run_id=run_id,
            output_dir=output_dir,
        )
        state.add_event(
            "RunStarted",
            {
                "task": task,
                "workspace_root": str(state.workspace.root),
                "budgets": state.budgets.to_json_dict(),
            },
        )
        if "shell" in self.tools:
            state.shell_preflight = shell_preflight()
            state.add_event("ShellPreflight", state.shell_preflight)

        try:
            self._run_loop(state)
        except Exception as exc:  # pragma: no cover - defensive boundary
            state.fail(f"Unhandled exception: {exc}")
        finally:
            capture_final_diff(state)
            write_run_outputs(state)

        return state

    def _run_loop(self, state: RunState) -> None:
        while not state.done:
            if self._budget_exhausted(state):
                return
            if not self.profile.should_continue(state):
                state.finish("Run finished by profile.")
                return

            visible_tools = list(self.profile.visible_tools(state, self.tools))
            visible_tool_names = frozenset(tool.name for tool in visible_tools)
            built_context = self._build_context(state, visible_tools)
            if self._should_compact(state):
                self._compact(state)
                built_context = self._build_context(state, visible_tools)
            messages = built_context.messages
            state.add_event(
                "ContextBuilt",
                {
                    "message_count": len(messages),
                    "visible_tools": [tool.name for tool in visible_tools],
                    "token_estimate": built_context.token_estimate,
                    "static_context_chars": built_context.static_context_chars,
                    "tool_context_chars": built_context.tool_context_chars,
                    "project_instruction_chars": built_context.project_instruction_chars,
                    "context_artifacts": [artifact.path for artifact in built_context.artifacts],
                    "compaction_count": state.compaction_count,
                    "checkpoint_artifact": state.context_checkpoint_artifact or None,
                },
            )
            model_call_index = state.turn_count + 1
            context_artifact, request_artifact = write_model_request_artifacts(
                state,
                call_index=model_call_index,
                provider=self.model.name,
                messages=messages,
                tools=visible_tools,
            )
            http_request_artifact = self._write_provider_payload_artifact(
                state,
                call_index=model_call_index,
                messages=messages,
                tools=visible_tools,
            )
            state.add_event(
                "ModelRequest",
                {
                    "provider": self.model.name,
                    "base_url": _provider_base_url(self.model),
                    "message_count": len(messages),
                    "tool_count": len(visible_tools),
                    "context_artifact": context_artifact,
                    "logical_request_artifact": request_artifact,
                    "http_request_artifact": http_request_artifact,
                },
            )

            try:
                response = self.model.complete(messages, visible_tools, state)
            except Exception as exc:
                state.fail(f"Model provider error: {exc}")
                return
            state.turn_count += 1
            response_artifact = write_model_response_artifact(
                state,
                call_index=model_call_index,
                response=response,
            )
            state.add_event(
                "ModelResponse",
                {
                    "content_length": len(response.content),
                    "tool_call_count": len(response.tool_calls),
                    "finish_reason": response.finish_reason,
                    "response_artifact": response_artifact,
                },
            )

            if not response.tool_calls:
                if response.content:
                    state.finish(response.content)
                else:
                    state.fail("Model returned no content and no tool calls.")
                return

            for call in response.tool_calls:
                if self._tool_budget_exhausted(state):
                    return
                self._dispatch_tool_call(state, call, visible_tool_names=visible_tool_names)
                if state.done:
                    return

            if self.profile.should_finish(state):
                state.finish(response.content or state.summary or "Run finished by profile.")
                return

    def _dispatch_tool_call(self, state: RunState, call: ToolCall, *, visible_tool_names: frozenset[str]) -> None:
        args_preview = _small_event_data(call.args)
        state.add_event(
            "ToolCallRequested",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "args": args_preview,
                "args_preview": args_preview,
            },
        )
        state.tool_call_count += 1

        tool = self.tools.get(call.name)
        if tool is None:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=f"Unknown tool requested: {call.name}",
                ok=False,
                data={"error_type": "UnknownTool", "available_tools": sorted(self.tools)},
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            return

        if call.name not in visible_tool_names:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=f"Tool is not visible for this profile: {call.name}",
                ok=False,
                data={"blocked": True, "error_type": "ToolNotVisible", "visible_tools": sorted(visible_tool_names)},
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            return

        try:
            decision = self.policy.evaluate(call, state)
        except Exception as exc:
            decision = PolicyDecision.deny(f"Policy engine error: {exc}")
            self._record_policy_decision(state, call, decision)
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=decision.reason,
                ok=False,
                data={"blocked": True, "error_type": type(exc).__name__},
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            state.fail(decision.reason)
            return

        self._record_policy_decision(state, call, decision)
        if not decision.allowed:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=decision.reason or "Policy denied tool call.",
                ok=False,
                data={"blocked": True},
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            return

        state.add_event("ToolCallStarted", {"tool_call_id": call.id, "tool": call.name})
        try:
            result = self.executor.run_tool(tool, call, state)
        except Exception as exc:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=f"Tool error: {exc}",
                ok=False,
                data={"error_type": type(exc).__name__},
            )
        if not result.call_id:
            result = ToolResult(
                tool_name=result.tool_name,
                output=result.output,
                call_id=call.id,
                ok=result.ok,
                data=result.data,
            )
        self._append_tool_step(state, call, result)
        self._record_tool_result(state, call, result)

    def _record_tool_result(self, state: RunState, call: ToolCall, result: ToolResult) -> None:
        output_limit = state.budgets.max_command_output_chars_visible
        output = result.output[:output_limit]
        output_chars = _output_chars(result)
        state.add_event(
            "ToolCallFinished",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "ok": result.ok,
                "blocked": bool(result.data.get("blocked")),
                "output": output,
                "output_chars": output_chars,
                "output_truncated": output_chars > len(output),
                "data": _small_event_data(result.data),
            },
        )

    def _append_tool_step(self, state: RunState, call: ToolCall, result: ToolResult) -> None:
        state.tool_steps.append(ToolStep(call=call, result=result))

    def _record_policy_decision(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> None:
        state.add_event(
            "PolicyDecision",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "redacted": decision.redacted,
            },
        )

    def _budget_exhausted(self, state: RunState) -> bool:
        if state.elapsed_seconds() > state.budgets.max_run_seconds:
            state.fail("Run exceeded max_run_seconds budget.")
            return True
        if state.turn_count >= state.budgets.max_turns:
            state.fail("Run exceeded max_turns budget.")
            return True
        if state.tool_call_count >= state.budgets.max_tool_calls:
            state.fail("Run exceeded max_tool_calls budget.")
            return True
        return False

    def _tool_budget_exhausted(self, state: RunState) -> bool:
        if state.tool_call_count >= state.budgets.max_tool_calls:
            state.fail("Run exceeded max_tool_calls budget.")
            return True
        return False

    def _write_provider_payload_artifact(
        self,
        state: RunState,
        *,
        call_index: int,
        messages: list[Message],
        tools: list[Tool],
    ) -> str | None:
        build_payload = getattr(self.model, "build_payload", None)
        if not callable(build_payload):
            return None
        payload = build_payload(messages, tools, state)
        if not isinstance(payload, dict):
            return None
        return write_model_http_request_artifact(state, call_index=call_index, payload=payload)

    def _build_context(self, state: RunState, visible_tools: list[Tool]) -> BuiltContext:
        build_context = getattr(self.profile, "build_context", None)
        if callable(build_context):
            built_context = build_context(state)
        else:
            messages = list(self.profile.build_messages(state))
            built_context = BuiltContext(
                messages=messages,
                token_estimate=estimate_messages_tokens(messages),
                static_context_chars=sum(len(message_text(message)) for message in messages),
                tool_context_chars=0,
                project_instruction_chars=0,
            )
        token_estimate = built_context.token_estimate + estimate_tools_tokens(visible_tools)
        state.context_token_estimate = token_estimate
        return replace(built_context, token_estimate=token_estimate)

    def _should_compact(self, state: RunState) -> bool:
        should_compact = getattr(self.profile, "should_compact", None)
        return callable(should_compact) and bool(should_compact(state))

    def _compact(self, state: RunState) -> None:
        state.add_event(
            "CompactionStarted",
            {
                "profile": self.profile.name,
                "token_estimate": state.context_token_estimate,
                "tool_step_count": len(state.tool_steps),
            },
        )
        self.profile.compact(state)
        state.add_event(
            "CompactionFinished",
            {
                "profile": self.profile.name,
                "compaction_count": state.compaction_count,
                "checkpoint_artifact": state.context_checkpoint_artifact or None,
            },
        )


def _small_event_data(data: dict[str, Any]) -> dict[str, Any]:
    safe = json_safe(data)
    encoded = json.dumps(safe, sort_keys=True)
    if len(encoded) <= MAX_EVENT_DATA_CHARS:
        return safe
    return {
        "_truncated": True,
        "json_chars": len(encoded),
        "preview": encoded[:MAX_EVENT_DATA_CHARS],
    }


def _output_chars(result: ToolResult) -> int:
    value = result.data.get("output_chars")
    return value if isinstance(value, int) else len(result.output)


def _provider_base_url(model: ModelProvider) -> str | None:
    config = getattr(model, "config", None)
    value = getattr(config, "base_url", None)
    return value if isinstance(value, str) else None
