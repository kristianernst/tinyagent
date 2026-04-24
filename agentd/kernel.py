"""Minimal tinyagent kernel loop."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from agentd.contracts import Executor, LocalExecutor, ModelProvider, PolicyEngine, Profile, Tool
from agentd.output import write_model_request_artifacts, write_model_response_artifact, write_run_outputs
from agentd.state import PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult, Workspace


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

        try:
            self._run_loop(state)
        except Exception as exc:  # pragma: no cover - defensive boundary
            state.fail(f"Unhandled exception: {exc}")
        finally:
            write_run_outputs(state)

        return state

    def _run_loop(self, state: RunState) -> None:
        while not state.done:
            if self._budget_exhausted(state):
                return
            if not self.profile.should_continue(state):
                state.finish("Run finished by profile.")
                return

            messages = list(self.profile.build_messages(state))
            visible_tools = list(self.profile.visible_tools(state, self.tools))
            state.add_event(
                "ContextBuilt",
                {
                    "message_count": len(messages),
                    "visible_tools": [tool.name for tool in visible_tools],
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
            state.add_event(
                "ModelRequest",
                {
                    "provider": self.model.name,
                    "message_count": len(messages),
                    "tool_count": len(visible_tools),
                    "context_artifact": context_artifact,
                    "request_artifact": request_artifact,
                },
            )

            response = self.model.complete(messages, visible_tools, state)
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

            for call in response.tool_calls:
                if self._tool_budget_exhausted(state):
                    return
                self._dispatch_tool_call(state, call)
                if state.done:
                    return

            if self.profile.should_finish(state):
                state.finish(response.content or state.summary or "Run finished by profile.")
                return

            self.profile.compact(state)

    def _dispatch_tool_call(self, state: RunState, call: ToolCall) -> None:
        state.add_event(
            "ToolCallRequested",
            {
                "tool_call_id": call.id,
                "tool": call.name,
            },
        )

        decision = self.policy.evaluate(call, state)
        self._record_policy_decision(state, call, decision)
        if not decision.allowed:
            state.tool_results.append(
                ToolResult(tool_name=call.name, output=decision.reason or "Policy denied tool call.", ok=False)
            )
            return

        tool = self.tools.get(call.name)
        if tool is None:
            state.fail(f"Unknown tool requested: {call.name}")
            return

        state.add_event("ToolCallStarted", {"tool_call_id": call.id, "tool": call.name})
        result = self.executor.run_tool(tool, call, state)
        state.tool_call_count += 1
        state.tool_results.append(result)
        state.add_event(
            "ToolCallFinished",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "ok": result.ok,
                "finish": result.finish,
            },
        )

        if result.finish:
            state.finish(result.output)

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
