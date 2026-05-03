"""Minimal tinyagent kernel loop."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from agentd.context import BuiltContext, estimate_messages_tokens, estimate_tools_tokens, message_text
from agentd.contextfs import refresh_contextfs
from agentd.contracts import ApprovalHandler, Executor, LocalExecutor, ModelProvider, PolicyEngine, Profile, Tool
from agentd.events import EventSink, json_safe
from agentd.hooks import TinyHook
from agentd.model_stream import complete_model_call
from agentd.observations import extract_observations
from agentd.output import (
    capture_final_diff,
    write_context_report_artifact,
    write_model_http_request_artifact,
    write_model_request_artifacts,
    write_model_response_artifact,
    write_run_outputs,
)
from agentd.run_control import CancelToken, RunCancelled
from agentd.state import (
    ApprovalGrant,
    ApprovalMode,
    ApprovalRequest,
    ApprovalResolution,
    FinishDecision,
    Message,
    PolicyDecision,
    RunBudgets,
    RunState,
    ToolCall,
    ToolResult,
    ToolStep,
)
from agentd.tools.builtins.shell import shell_preflight
from agentd.workspace import SandboxMode, WorkspaceMode, prepare_workspace

MAX_EVENT_DATA_CHARS = 4_000
HookErrorPolicy = Literal["fail", "record"]


class Kernel:
    """Small runtime that owns state, model calls, policy checks, and tool dispatch."""

    def __init__(
        self,
        *,
        model: ModelProvider,
        profile: Profile,
        tools: Iterable[Tool],
        policy: PolicyEngine,
        approval_handler: ApprovalHandler | None = None,
        executor: Executor | None = None,
        budgets: RunBudgets | None = None,
        stream: bool = False,
        event_sink: EventSink | None = None,
        approval_mode: ApprovalMode = "yolo",
        workspace_mode: WorkspaceMode = "auto",
        sandbox_mode: SandboxMode = "none",
        hooks: Sequence[TinyHook] = (),
        hook_error_policy: HookErrorPolicy = "fail",
    ) -> None:
        self.model = model
        self.profile = profile
        self.tools = {tool.name: tool for tool in tools}
        self.policy = policy
        self.approval_handler = approval_handler
        self.executor = executor or LocalExecutor()
        self.budgets = budgets or RunBudgets()
        self.stream = stream
        self.event_sink = event_sink
        self.approval_mode = approval_mode
        self.workspace_mode = workspace_mode
        self.sandbox_mode = sandbox_mode
        self.hooks = tuple(hooks)
        self.hook_error_policy = hook_error_policy

    def run(
        self,
        task: str,
        *,
        workspace: Path | str,
        run_id: str | None = None,
        output_dir: Path | None = None,
        stream: bool | None = None,
        event_sink: EventSink | None = None,
        cancel_token: CancelToken | None = None,
        workspace_mode: WorkspaceMode | None = None,
        approval_mode: ApprovalMode | None = None,
        sandbox_mode: SandboxMode | None = None,
        parent_run_id: str | None = None,
        parent_event_id: str | None = None,
        branch_name: str | None = None,
    ) -> RunState:
        resolved_run_id = run_id or f"run_{uuid4().hex}"
        prepared_workspace = prepare_workspace(
            Path(workspace),
            mode=workspace_mode or self.workspace_mode,
            run_id=resolved_run_id,
            sandbox_mode=sandbox_mode or self.sandbox_mode,
        )
        resolved_output_dir = output_dir
        if resolved_output_dir is None:
            resolved_output_dir = prepared_workspace.envelope.original_root / ".tinyagent" / "runs" / resolved_run_id
        state = RunState.create(
            task,
            prepared_workspace.workspace,
            budgets=self.budgets,
            run_id=resolved_run_id,
            output_dir=resolved_output_dir,
            parent_run_id=parent_run_id,
            parent_event_id=parent_event_id,
            branch_name=branch_name,
        )
        state.workspace_envelope = prepared_workspace.envelope
        state.approval_mode = approval_mode or self.approval_mode
        state.status = "running"
        if cancel_token is not None:
            state.cancel_token = cancel_token
        use_stream = self.stream if stream is None else stream
        state.stream_sink = event_sink if event_sink is not None else self.event_sink

        try:
            self._run_hooks(state, "on_run_start", state)
            state.emit(
                "run.started",
                {
                    "task": task,
                    "workspace_root": str(state.workspace.root),
                    "original_workspace_root": (
                        str(state.workspace_envelope.original_root)
                        if state.workspace_envelope
                        else str(Path(workspace).expanduser().resolve())
                    ),
                    "budgets": state.budgets.to_json_dict(),
                    "stream": use_stream,
                    "workspace_mode": state.workspace_envelope.mode if state.workspace_envelope else (workspace_mode or self.workspace_mode),
                    "approval_mode": state.approval_mode,
                    "sandbox_mode": state.workspace_envelope.sandbox_mode if state.workspace_envelope else (sandbox_mode or self.sandbox_mode),
                    "sandbox_enforced": bool(state.workspace_envelope.sandbox_enforced) if state.workspace_envelope else False,
                    "parent_run_id": state.parent_run_id,
                    "parent_event_id": state.parent_event_id,
                    "branch_name": state.branch_name,
                },
            )
            self._emit_workspace_boundary(state, prepared_workspace.worktree_created)
            if "shell" in self.tools:
                state.shell_preflight = shell_preflight()
                state.emit("shell.preflight.completed", state.shell_preflight)
            index_path = refresh_contextfs(state)
            state.emit("contextfs.index.updated", {"path": index_path, "phase": "startup"})
            state.raise_if_cancelled()
            state.start_turn("turn-0001")
            self._run_loop(state, stream=use_stream)
        except RunCancelled as exc:
            state.request_cancel(
                str(exc) or "cancelled",
                source="sigint" if state.cancel_token.reason == "sigint" else "harness",
                escalate=state.cancel_token.escalated,
            )
        except Exception as exc:  # pragma: no cover - defensive boundary
            state.fail(f"Unhandled exception: {exc}")
        finally:
            self._finalize_artifacts(state)
            state.finish_turn()
            self._finalize_run(state)
            write_run_outputs(state)

        return state

    def _run_loop(self, state: RunState, *, stream: bool) -> None:
        while not state.done:
            state.raise_if_cancelled()
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
            built_context = self._on_context(state, built_context)
            messages = built_context.messages
            messages, visible_tools = self._before_model_call(state, messages, visible_tools)
            visible_tool_names = frozenset(tool.name for tool in visible_tools)
            actual_token_estimate = estimate_messages_tokens(messages) + estimate_tools_tokens(visible_tools)
            built_context = replace(built_context, messages=messages, token_estimate=actual_token_estimate)
            state.context_token_estimate = actual_token_estimate
            state.emit(
                "context.built",
                {
                    "message_count": len(messages),
                    "visible_tools": [tool.name for tool in visible_tools],
                    "token_estimate": built_context.token_estimate,
                    "static_context_chars": built_context.static_context_chars,
                    "tool_context_chars": built_context.tool_context_chars,
                    "project_instruction_chars": built_context.project_instruction_chars,
                    "context_artifacts": [artifact.path for artifact in built_context.artifacts],
                    "context_report_artifact": None,
                    "contextfs_index_path": built_context.contextfs_index_path,
                    "compaction_count": state.compaction_count,
                    "checkpoint_artifact": state.context_checkpoint_artifact or None,
                },
            )
            model_call_index = state.model_call_count + 1
            model_call_id = f"model-call-{model_call_index:04d}"
            context_report_artifact = write_context_report_artifact(
                state,
                call_index=model_call_index,
                built_context=built_context,
                budget=_context_budget(self.profile, state),
            )
            state.emit(
                "context.report.written",
                {
                    "model_call_id": model_call_id,
                    "model_call_index": model_call_index,
                    "context_report_artifact": context_report_artifact,
                    "included_count": len(built_context.included),
                    "excluded_count": len(built_context.excluded),
                    "contextfs_index_path": built_context.contextfs_index_path,
                },
            )
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
                stream=stream,
            )
            state.emit(
                "model.call.started",
                {
                    "provider": self.model.name,
                    "model_call_id": model_call_id,
                    "model_call_index": model_call_index,
                    "base_url": _provider_base_url(self.model),
                    "message_count": len(messages),
                    "tool_count": len(visible_tools),
                    "stream": stream,
                    "context_artifact": context_artifact,
                    "context_report_artifact": context_report_artifact,
                    "logical_request_artifact": request_artifact,
                    "http_request_artifact": http_request_artifact,
                },
            )

            try:
                state.start_step(
                    "model_call",
                    model_call_id,
                    model_call_id=model_call_id,
                    data={"provider": self.model.name, "model_call_index": model_call_index},
                )
                response = complete_model_call(
                    self.model,
                    messages,
                    visible_tools,
                    state,
                    call_index=model_call_index,
                    stream=stream,
                )
                response = self._after_model_response(state, response)
            except RunCancelled:
                state.emit(
                    "model.cancelled",
                    {
                        "provider": self.model.name,
                        "model_call_id": model_call_id,
                        "model_call_index": model_call_index,
                        "reason": state.cancel_reason or state.cancel_token.reason or "cancelled",
                    },
                    visibility="user",
                )
                state.finish_step("cancelled", data={"reason": state.cancel_reason or "cancelled"})
                raise
            except Exception as exc:
                event_type = _model_error_event_type(exc)
                state.emit(
                    event_type,
                    {
                        "provider": self.model.name,
                        "reason": str(exc),
                        "model_call_id": model_call_id,
                        "model_call_index": model_call_index,
                    },
                    visibility="user",
                )
                step_status = (
                    "idle_timeout"
                    if event_type == "model.idle_timeout"
                    else "timeout"
                    if event_type == "model.timeout"
                    else "failed"
                )
                state.finish_step(step_status)
                state.fail(f"Model provider error: {exc}")
                return
            state.model_call_count += 1
            self._record_model_tool_calls(
                state,
                response,
                provider=self.model.name,
                model_call_id=model_call_id,
                model_call_index=model_call_index,
            )
            response_artifact = write_model_response_artifact(
                state,
                call_index=model_call_index,
                response=response,
            )
            state.transcript.record_model_response(
                item_id=f"transcript-model-response-{model_call_index:04d}",
                turn_id=state.current_turn_id,
                model_call_id=model_call_id,
                provider=self.model.name,
                content_length=len(response.content),
                finish_reason=response.finish_reason,
                tool_call_count=len(response.tool_calls),
                response_artifact=response_artifact,
            )
            state.emit(
                "model.call.completed",
                {
                    "provider": self.model.name,
                    "model_call_id": model_call_id,
                    "model_call_index": model_call_index,
                    "content_length": len(response.content),
                    "tool_call_count": len(response.tool_calls),
                    "finish_reason": response.finish_reason,
                    "response_artifact": response_artifact,
                    "streamed": bool(response.raw.get("streamed")),
                },
            )
            state.finish_step("completed", data={"provider": self.model.name})

            if not response.tool_calls:
                if response.content:
                    decision = self._before_finish(state, response)
                    if decision.allow:
                        state.finish(response.content)
                    else:
                        state.finish_gate_messages.append(decision.injected_message or decision.reason)
                        state.transcript.record_finish_gate(
                            item_id=f"transcript-finish-gate-{len(state.transcript.items) + 1:04d}",
                            turn_id=state.current_turn_id,
                            reason=decision.reason,
                            injected_message=decision.injected_message,
                        )
                        state.emit(
                            "finish.blocked",
                            {"reason": decision.reason, "injected_message": decision.injected_message},
                            visibility="user",
                        )
                        state.finish_step("completed", data={"provider": self.model.name, "finish_blocked": True})
                        continue
                else:
                    state.fail("Model returned no content and no tool calls.")
                return

            for call in response.tool_calls:
                state.raise_if_cancelled()
                if self._tool_budget_exhausted(state):
                    return
                self._dispatch_tool_call(state, call, visible_tool_names=visible_tool_names)
                if state.done:
                    return

            if self.profile.should_finish(state):
                candidate = response.content or state.final_output or "Run finished by profile."
                decision = self._before_finish(state, ModelResponse(content=candidate, finish_reason=response.finish_reason))
                if decision.allow:
                    state.finish(candidate)
                else:
                    state.finish_gate_messages.append(decision.injected_message or decision.reason)
                    state.transcript.record_finish_gate(
                        item_id=f"transcript-finish-gate-{len(state.transcript.items) + 1:04d}",
                        turn_id=state.current_turn_id,
                        reason=decision.reason,
                        injected_message=decision.injected_message,
                    )
                    state.emit(
                        "finish.blocked",
                        {"reason": decision.reason, "injected_message": decision.injected_message},
                        visibility="user",
                    )
                    continue
                return

    def _dispatch_tool_call(self, state: RunState, call: ToolCall, *, visible_tool_names: frozenset[str]) -> None:
        state.raise_if_cancelled()
        state.tool_call_count += 1

        tool = self.tools.get(call.name)
        if tool is None:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=f"Unknown tool requested: {call.name}",
                ok=False,
                data={"error_type": "UnknownTool", "available_tools": sorted(self.tools)},
                failure_kind="invalid_tool_args",
                summary=f"Unknown tool requested: {call.name}",
                content_preview=f"Unknown tool requested: {call.name}",
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            self._record_tool_blocked(state, call, result.output)
            index_path = refresh_contextfs(state)
            state.emit("contextfs.index.updated", {"path": index_path, "tool_call_id": call.id})
            return

        if call.name not in visible_tool_names:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=f"Tool is not visible for this profile: {call.name}",
                ok=False,
                data={
                    "blocked": True,
                    "error_type": "ToolNotVisible",
                    "visible_tools": sorted(visible_tool_names),
                },
                failure_kind="policy_denied",
                summary=f"Tool is not visible for this profile: {call.name}",
                content_preview=f"Tool is not visible for this profile: {call.name}",
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            self._record_tool_blocked(state, call, result.output)
            index_path = refresh_contextfs(state)
            state.emit("contextfs.index.updated", {"path": index_path, "tool_call_id": call.id})
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
                failure_kind="policy_denied",
                summary=decision.reason,
                content_preview=decision.reason,
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            self._record_tool_blocked(state, call, result.output)
            index_path = refresh_contextfs(state)
            state.emit("contextfs.index.updated", {"path": index_path, "tool_call_id": call.id})
            state.fail(decision.reason)
            return

        self._record_policy_decision(state, call, decision)
        hook_result = self._before_tool_call(state, call, decision)
        if isinstance(hook_result, ToolResult):
            result = hook_result if hook_result.call_id else replace(hook_result, call_id=call.id)
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            self._record_tool_blocked(state, call, result.output)
            index_path = refresh_contextfs(state)
            state.emit("contextfs.index.updated", {"path": index_path, "tool_call_id": call.id})
            return
        if isinstance(hook_result, ToolCall):
            call = hook_result
            try:
                decision = self.policy.evaluate(call, state)
            except Exception as exc:
                decision = PolicyDecision.deny(f"Policy engine error after hook mutation: {exc}")
            self._record_policy_decision(state, call, decision)
            tool = self.tools.get(call.name)
            if tool is None or call.name not in visible_tool_names:
                reason = f"Hook mutated tool call to unavailable or hidden tool: {call.name}"
                result = ToolResult(
                    tool_name=call.name,
                    call_id=call.id,
                    output=reason,
                    ok=False,
                    data={"blocked": True, "error_type": "HookMutatedToolNotVisible"},
                    failure_kind="policy_denied",
                    summary=reason,
                    content_preview=reason,
                )
                self._append_tool_step(state, call, result)
                self._record_tool_result(state, call, result)
                self._record_tool_blocked(state, call, result.output)
                index_path = refresh_contextfs(state)
                state.emit("contextfs.index.updated", {"path": index_path, "tool_call_id": call.id})
                return
        if decision.kind == "needs_approval":
            decision = self._resolve_approval(state, call, decision)
            if decision.kind == "deny":
                self._record_policy_decision(state, call, decision)
        if not decision.allowed:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=decision.reason or "Policy denied tool call.",
                ok=False,
                data={"blocked": True},
                failure_kind="policy_denied",
                summary=decision.reason or "Policy denied tool call.",
                content_preview=decision.reason or "Policy denied tool call.",
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            self._record_tool_blocked(state, call, result.output)
            index_path = refresh_contextfs(state)
            state.emit("contextfs.index.updated", {"path": index_path, "tool_call_id": call.id})
            return

        tool_execution_id = f"tool-exec-{call.id}"
        self._record_mutation_event(state, "workspace.mutation.planned", call)
        self._record_mutation_event(state, "workspace.mutation.started", call)
        state.emit("tool.execution.started", {"tool_call_id": call.id, "tool_execution_id": tool_execution_id, "tool": call.name})
        state.start_step("tool_execution", tool_execution_id, data={"tool_call_id": call.id, "tool": call.name})
        try:
            result = self.executor.run_tool(tool, call, state)
        except RunCancelled as exc:
            state.request_cancel(
                str(exc) or "cancelled",
                source="sigint" if state.cancel_token.reason == "sigint" else "harness",
                escalate=state.cancel_token.escalated,
            )
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=state.cancel_reason or "cancelled",
                ok=False,
                data={"cancelled": True, "reason": state.cancel_reason or "cancelled"},
                failure_kind="unknown",
                summary=state.cancel_reason or "cancelled",
                content_preview=state.cancel_reason or "cancelled",
            )
        except Exception as exc:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=f"Tool error: {exc}",
                ok=False,
                data={"error_type": type(exc).__name__},
                failure_kind="unknown",
                summary=f"Tool error: {exc}",
                content_preview=f"Tool error: {exc}",
            )
        result = self._after_tool_result(state, result)
        if not result.call_id:
            result = replace(result, call_id=call.id)
        self._append_tool_step(state, call, result)
        self._record_tool_result(state, call, result)
        index_path = refresh_contextfs(state)
        state.emit("contextfs.index.updated", {"path": index_path, "tool_call_id": call.id})
        if result.data.get("cancelled"):
            state.finish_step("cancelled", data={"reason": result.data.get("reason") or "cancelled"})
        elif result.ok:
            state.finish_step("completed", data={"tool_call_id": call.id, "tool": call.name})
        else:
            state.finish_step("failed", data={"tool_call_id": call.id, "tool": call.name})
        self._record_mutation_event(state, "workspace.mutation.completed", call, ok=result.ok)
        if result.data.get("cancelled"):
            state.request_cancel(str(result.data.get("reason") or state.cancel_reason or "cancelled"))

    def _record_tool_result(self, state: RunState, call: ToolCall, result: ToolResult) -> None:
        if result.data.get("cancelled"):
            state.emit(
                "tool.execution.cancelled",
                {
                    "tool_call_id": call.id,
                    "tool": call.name,
                    "reason": result.data.get("reason") or state.cancel_reason or "cancelled",
                    "output": result.output[: state.budgets.max_command_output_chars_visible],
                    "output_chars": _output_chars(result),
                    "artifact_path": result.artifact_path,
                    "failure_kind": result.failure_kind or result.data.get("failure_kind"),
                    "data": _small_event_data(result.data),
                },
                visibility="user",
            )
            return
        output_limit = state.budgets.max_command_output_chars_visible
        output = result.output[:output_limit]
        output_chars = _output_chars(result)
        if result.artifact_path or result.data.get("output_artifact"):
            state.emit(
                "tool.execution.output.snapshot",
                {
                    "tool_call_id": call.id,
                    "tool": call.name,
                    "output_chars": output_chars,
                    "artifact_path": result.artifact_path,
                    "output_artifact": result.data.get("output_artifact"),
                    "context_artifact": result.data.get("context_artifact"),
                },
            )
        payload = {
            "tool_call_id": call.id,
            "tool": call.name,
            "ok": result.ok,
            "blocked": bool(result.data.get("blocked")),
            "output": output,
            "output_chars": output_chars,
            "output_truncated": output_chars > len(output),
            "data": _small_event_data(result.data),
        }
        if result.artifact_path:
            payload["artifact_path"] = result.artifact_path
        failure_kind = result.failure_kind or result.data.get("failure_kind")
        if failure_kind:
            payload["failure_kind"] = failure_kind
        if result.read_hints:
            payload["read_hints"] = result.read_hints
        state.emit("tool.execution.completed" if result.ok else "tool.execution.failed", payload)

    def _append_tool_step(self, state: RunState, call: ToolCall, result: ToolResult) -> None:
        artifact_refs = tuple(
            ref
            for ref in (
                result.artifact_path,
                result.data.get("context_artifact"),
                result.data.get("output_artifact"),
            )
            if isinstance(ref, str) and ref
        )
        state.transcript.record_tool_result(
            item_id=f"transcript-tool-result-{len(state.tool_steps) + 1:04d}",
            turn_id=state.current_turn_id,
            tool_call_id=result.call_id or call.id,
            tool_name=result.tool_name or call.name,
            ok=result.ok,
            summary=result.summary or _first_line(result.output) or ("ok" if result.ok else "failed"),
            failure_kind=result.failure_kind or result.data.get("failure_kind"),
            artifact_refs=artifact_refs,
            synthetic=bool(result.data.get("blocked") or result.data.get("progress_blocked")),
            data={
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
                "truncated": result.truncated,
            },
        )
        state.tool_steps.append(ToolStep(call=call, result=result))
        for observation in extract_observations(call, result, state):
            state.observations.append(observation)
            state.emit(
                "observation.recorded",
                observation.to_json_dict(),
                artifact_refs=list(observation.refs),
            )

    def _record_policy_decision(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> None:
        approval_id = decision.approval.approval_id if decision.approval else None
        state.emit(
            "policy.evaluated",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "kind": decision.kind,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "redacted": decision.redacted,
                "approval_id": approval_id,
                "matched_rule": decision.matched_rule,
                "permission": decision.permission,
            },
        )

    def _record_tool_blocked(self, state: RunState, call: ToolCall, reason: str) -> None:
        state.emit(
            "tool.execution.blocked",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "reason": reason,
            },
            visibility="user",
        )

    def _resolve_approval(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> PolicyDecision:
        approval = decision.approval
        if approval is None:
            return PolicyDecision.deny(decision.reason or "approval request missing")

        grant = state.approval_grants.get(approval.grant_key())
        if grant is not None:
            state.emit(
                "approval.resolved",
                {
                    "approval_id": approval.approval_id,
                    "decision": "approved",
                    "scope": grant.scope,
                    "reason": "approval_grant",
                },
                visibility="user",
            )
            return PolicyDecision.allow("approved by run-scoped grant")

        state.pending_approvals[approval.approval_id] = approval
        state.emit("approval.requested", approval.to_json_dict(), visibility="user")

        if state.approval_mode == "never":
            resolution = ApprovalResolution(
                approval_id=approval.approval_id,
                decision="denied",
                reason="approval_mode_never",
            )
        elif state.approval_mode == "yolo":
            resolution = _yolo_resolution(approval)
        elif self.approval_handler is not None:
            state.start_step("approval_wait", f"approval-{approval.approval_id}", data={"approval_id": approval.approval_id})
            try:
                resolution = self.approval_handler.resolve(approval, state)
            except RunCancelled:
                state.finish_step("cancelled", data={"approval_id": approval.approval_id})
                raise
            except Exception as exc:
                resolution = ApprovalResolution(
                    approval_id=approval.approval_id,
                    decision="denied",
                    reason=f"approval handler error: {exc}",
                )
            else:
                state.finish_step("completed", data={"approval_id": approval.approval_id, "decision": resolution.decision})
        else:
            resolution = ApprovalResolution(
                approval_id=approval.approval_id,
                decision="denied",
                reason="approval_handler_unavailable",
            )

        state.pending_approvals.pop(approval.approval_id, None)
        state.emit("approval.resolved", resolution.to_json_dict(), visibility="user")
        if resolution.decision == "approved":
            if resolution.scope == "run":
                state.approval_grants[approval.grant_key()] = ApprovalGrant(
                    approval_id=approval.approval_id,
                    grant_key=approval.grant_key(),
                    scope="run",
                )
            return PolicyDecision.allow(resolution.reason or "approved")
        return PolicyDecision.deny(resolution.reason or f"approval {resolution.decision}")

    def _record_model_tool_calls(
        self,
        state: RunState,
        response,
        *,
        provider: str,
        model_call_id: str,
        model_call_index: int,
    ) -> None:
        for call in response.tool_calls:
            already = any(
                event.type == "model.tool_call.assembly.completed" and event.data.get("tool_call_id") == call.id
                for event in state.events
            )
            if already:
                continue
            state.emit(
                "model.tool_call.assembly.started",
                {
                    "provider": provider,
                    "model_call_id": model_call_id,
                    "model_call_index": model_call_index,
                    "tool_call_id": call.id,
                    "tool": call.name,
                },
            )
            state.emit(
                "model.tool_call.assembly.completed",
                {
                    "provider": provider,
                    "model_call_id": model_call_id,
                    "model_call_index": model_call_index,
                    "tool_call_id": call.id,
                    "tool": call.name,
                    "args": _small_event_data(call.args),
                },
            )
            state.transcript.record_tool_call(
                item_id=f"transcript-tool-call-{len(state.transcript.items) + 1:04d}",
                turn_id=state.current_turn_id,
                model_call_id=model_call_id,
                tool_call_id=call.id,
                tool_name=call.name,
                args=_small_event_data(call.args),
            )

    def _record_mutation_event(self, state: RunState, event_type: str, call: ToolCall, *, ok: bool | None = None) -> None:
        if call.name not in {"apply_patch", "shell"}:
            return
        data: dict[str, Any] = {
            "tool_call_id": call.id,
            "tool": call.name,
            "workspace_root": str(state.workspace.root),
        }
        if ok is not None:
            data["ok"] = ok
        state.emit(event_type, data)

    def _budget_exhausted(self, state: RunState) -> bool:
        if state.elapsed_seconds() > state.budgets.max_run_seconds:
            state.fail("Run exceeded max_run_seconds budget.")
            return True
        if state.model_call_count >= state.budgets.max_turns:
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
        stream: bool = False,
    ) -> str | None:
        build_payload = getattr(self.model, "build_stream_payload" if stream else "build_payload", None)
        if not callable(build_payload):
            return None
        payload = build_payload(messages, tools, state)
        if not isinstance(payload, dict):
            return None
        return write_model_http_request_artifact(state, call_index=call_index, payload=payload)

    def _emit_workspace_boundary(self, state: RunState, worktree_created: bool) -> None:
        envelope = state.workspace_envelope
        if envelope is None:
            return
        state.emit(
            "workspace.opened",
            {
                "root": str(envelope.root),
                "original_root": str(envelope.original_root),
                "mode": envelope.mode,
                "effective_mode": envelope.effective_mode,
            },
        )
        dirty = envelope.dirty_state_before
        if dirty.is_git_repo and not dirty.clean:
            state.emit("workspace.dirty.detected", dirty.to_json_dict(), visibility="user")
        if worktree_created:
            state.emit(
                "worktree.created",
                {
                    "path": str(envelope.worktree_path),
                    "git_head": envelope.git_head_before,
                    "original_root": str(envelope.original_root),
                },
                visibility="user",
            )
        state.emit("workspace.boundary", envelope.to_json_dict(), visibility="user")

    def _finalize_message(self, state: RunState) -> None:
        if not state.done and not state.failed and not state.cancelled:
            state.finish("Run finished without explicit final output.")
        if not state.final_output:
            return
        if any(event.type == "model.message.completed" and event.data.get("output_path") == "final.md" for event in state.events):
            return
        state.emit(
            "model.message.completed",
            {
                "role": "assistant",
                "content_chars": len(state.final_output),
                "output_path": "final.md",
            },
            visibility="user",
        )

    def _finalize_artifacts(self, state: RunState) -> None:
        state.finalization_attempted = True
        state.start_step("artifact_finalization", "artifact-finalization-0001")
        state.emit("artifact.finalization.started", {"output_dir": str(state.output_dir)})
        try:
            self._finalize_message(state)
            capture_final_diff(state)
            for path in ("final.md", "metrics.json", "final.diff"):
                state.emit("artifact.materialized", {"path": path, "kind": "run_output"})
            state.emit("artifact.finalization.completed", {"output_dir": str(state.output_dir)})
            state.finish_step("completed")
        except Exception as exc:  # pragma: no cover - defensive finalization boundary
            state.emit("artifact.finalization.failed", {"reason": str(exc)}, visibility="user")
            state.finish_step("failed", data={"reason": str(exc)})
            if not state.failed and not state.cancelled:
                state.fail(f"artifact finalization failed: {exc}")
        finally:
            index_path = refresh_contextfs(state)
            state.emit("contextfs.index.updated", {"path": index_path, "phase": "finalization"})

    def _finalize_run(self, state: RunState) -> None:
        event_type = "run.cancelled" if state.cancelled else "run.failed" if state.failed else "run.completed"
        if any(event.type == event_type for event in state.events):
            return
        data = {
            "status": "cancelled" if state.cancelled else "failed" if state.failed else "completed",
            "turn_count": state.turn_count,
            "model_call_count": state.model_call_count,
            "tool_call_count": state.tool_call_count,
            "final_output_chars": len(state.final_output),
            "duration_seconds": state.elapsed_seconds(),
            "workspace_mode": state.workspace_envelope.mode if state.workspace_envelope else None,
            "workspace_effective_mode": state.workspace_envelope.effective_mode if state.workspace_envelope else None,
            "approval_mode": state.approval_mode,
            "sandbox_mode": state.workspace_envelope.sandbox_mode if state.workspace_envelope else "none",
            "sandbox_enforced": state.workspace_envelope.sandbox_enforced if state.workspace_envelope else False,
            "finalization_attempted": state.finalization_attempted,
        }
        if state.cancelled:
            data["reason"] = state.cancel_reason or "cancelled"
            data["current_step_kind"] = state.current_step_kind
            data["current_step_id"] = state.current_step_id
            data["escalated"] = state.cancel_escalated
            data["signal_count"] = max(state.cancel_signal_count, state.cancel_token.signal_count)
        if state.failed:
            data["reason"] = state.failure_reason or "Unknown failure"
        if state.cancelled:
            state.status = "cancelled"
        state.emit(event_type, data)
        refresh_contextfs(state)

    def _build_context(self, state: RunState, visible_tools: list[Tool]) -> BuiltContext:
        index_path = refresh_contextfs(state)
        state.emit("contextfs.index.updated", {"path": index_path})
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
        state.emit(
            "compaction.started",
            {
                "profile": self.profile.name,
                "token_estimate": state.context_token_estimate,
                "tool_step_count": len(state.tool_steps),
            },
        )
        self._run_hooks(state, "before_compact", state)
        self.profile.compact(state)
        state.transcript.record_compaction(
            item_id=f"transcript-compaction-{state.compaction_count:04d}",
            turn_id=state.current_turn_id,
            compaction_count=state.compaction_count,
            checkpoint_artifact=state.context_checkpoint_artifact or None,
        )
        state.emit(
            "checkpoint.completed",
            {
                "profile": self.profile.name,
                "compaction_count": state.compaction_count,
                "checkpoint_artifact": state.context_checkpoint_artifact or None,
            },
        )

    def _before_finish(self, state: RunState, response: ModelResponse) -> FinishDecision:
        before_finish = getattr(self.profile, "before_finish", None)
        decision = before_finish(state, response) if callable(before_finish) else FinishDecision.allowed()
        for hook in self.hooks:
            method = getattr(hook, "before_finish", None)
            if not callable(method):
                continue
            name = _hook_name(hook)
            state.emit("hook.started", {"hook": name, "method": "before_finish"})
            try:
                decision = method(state, response, decision)
            except Exception as exc:
                state.emit("hook.failed", {"hook": name, "method": "before_finish", "reason": str(exc)}, visibility="user")
                self._handle_hook_error(state, name, "before_finish", exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": "before_finish"})
        return decision

    def _run_hooks(self, state: RunState, method_name: str, *args) -> None:
        for hook in self.hooks:
            method = getattr(hook, method_name, None)
            if not callable(method):
                continue
            name = _hook_name(hook)
            state.emit("hook.started", {"hook": name, "method": method_name})
            try:
                method(*args)
            except Exception as exc:
                state.emit("hook.failed", {"hook": name, "method": method_name, "reason": str(exc)}, visibility="user")
                self._handle_hook_error(state, name, method_name, exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": method_name})

    def _on_context(self, state: RunState, built_context: BuiltContext) -> BuiltContext:
        current = built_context
        for hook in self.hooks:
            method = getattr(hook, "on_context", None)
            if not callable(method):
                continue
            name = _hook_name(hook)
            state.emit("hook.started", {"hook": name, "method": "on_context"})
            try:
                current = method(state, current)
            except Exception as exc:
                state.emit("hook.failed", {"hook": name, "method": "on_context", "reason": str(exc)}, visibility="user")
                self._handle_hook_error(state, name, "on_context", exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": "on_context"})
        return current

    def _after_model_response(self, state: RunState, response: ModelResponse) -> ModelResponse:
        current = response
        for hook in self.hooks:
            method = getattr(hook, "after_model_response", None)
            if not callable(method):
                continue
            name = _hook_name(hook)
            state.emit("hook.started", {"hook": name, "method": "after_model_response"})
            try:
                current = method(state, current)
            except Exception as exc:
                state.emit("hook.failed", {"hook": name, "method": "after_model_response", "reason": str(exc)}, visibility="user")
                self._handle_hook_error(state, name, "after_model_response", exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": "after_model_response"})
        return current

    def _before_model_call(self, state: RunState, messages: list[Message], tools: list[Tool]) -> tuple[list[Message], list[Tool]]:
        current_messages: list[Message] = messages
        current_tools: list[Tool] = tools
        for hook in self.hooks:
            method = getattr(hook, "before_model_call", None)
            if not callable(method):
                continue
            name = _hook_name(hook)
            state.emit("hook.started", {"hook": name, "method": "before_model_call"})
            try:
                returned = method(state, current_messages, current_tools)
                if isinstance(returned, tuple) and len(returned) == 2:
                    current_messages = list(returned[0])
                    current_tools = list(returned[1])
            except Exception as exc:
                state.emit("hook.failed", {"hook": name, "method": "before_model_call", "reason": str(exc)}, visibility="user")
                self._handle_hook_error(state, name, "before_model_call", exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": "before_model_call"})
        return current_messages, current_tools

    def _before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolCall | ToolResult | None:
        current: ToolCall | ToolResult | None = call
        for hook in self.hooks:
            method = getattr(hook, "before_tool_call", None)
            if not callable(method):
                continue
            name = _hook_name(hook)
            state.emit("hook.started", {"hook": name, "method": "before_tool_call"})
            try:
                returned = method(state, current if isinstance(current, ToolCall) else call, decision)
                current = returned if returned is not None else current
            except Exception as exc:
                state.emit("hook.failed", {"hook": name, "method": "before_tool_call", "reason": str(exc)}, visibility="user")
                self._handle_hook_error(state, name, "before_tool_call", exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": "before_tool_call"})
            if isinstance(current, ToolResult):
                return current
        return current if isinstance(current, ToolCall) and current != call else None

    def _after_tool_result(self, state: RunState, result: ToolResult) -> ToolResult:
        current = result
        for hook in self.hooks:
            method = getattr(hook, "after_tool_result", None)
            if not callable(method):
                continue
            name = _hook_name(hook)
            state.emit("hook.started", {"hook": name, "method": "after_tool_result"})
            try:
                current = method(state, current)
            except Exception as exc:
                state.emit("hook.failed", {"hook": name, "method": "after_tool_result", "reason": str(exc)}, visibility="user")
                self._handle_hook_error(state, name, "after_tool_result", exc)
            else:
                state.emit("hook.completed", {"hook": name, "method": "after_tool_result"})
        return current

    def _handle_hook_error(self, state: RunState, hook_name: str, method_name: str, exc: Exception) -> None:
        if self.hook_error_policy == "record":
            return
        reason = f"hook {hook_name}.{method_name} failed: {exc}"
        state.fail(reason)
        raise RuntimeError(reason) from exc


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


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0][:240] if text.strip() else ""


def _output_chars(result: ToolResult) -> int:
    value = result.data.get("output_chars")
    return value if isinstance(value, int) else len(result.output)


def _context_budget(profile: Profile, state: RunState) -> int:
    config = getattr(profile, "context_config", None)
    budget = getattr(config, "effective_compact_at_tokens", None)
    if isinstance(budget, int):
        return budget
    return state.context_token_estimate


def _hook_name(hook: TinyHook) -> str:
    return str(getattr(hook, "name", hook.__class__.__name__))


def _yolo_resolution(approval: ApprovalRequest) -> ApprovalResolution:
    if approval.action_kind in {"network", "workspace_escape"}:
        return ApprovalResolution(
            approval_id=approval.approval_id,
            decision="denied",
            reason=f"approval-mode=yolo does not allow {approval.action_kind}",
        )
    return ApprovalResolution(
        approval_id=approval.approval_id,
        decision="approved",
        scope="once",
        reason="approval_mode_yolo_in_workspace",
    )


def _model_error_event_type(exc: Exception) -> str:
    text = str(exc).lower()
    if "idle" in text and "timeout" in text:
        return "model.idle_timeout"
    if "timed out" in text or "timeout" in text:
        return "model.timeout"
    return "model.call.failed"


def _provider_base_url(model: ModelProvider) -> str | None:
    config = getattr(model, "config", None)
    value = getattr(config, "base_url", None)
    return value if isinstance(value, str) else None
