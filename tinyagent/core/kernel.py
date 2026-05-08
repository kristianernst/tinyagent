"""Minimal tinyagent kernel loop."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from tinyagent.core.context import BuiltContext, estimate_messages_tokens, estimate_tools_tokens, message_text
from tinyagent.core.context_sources import ContextReadTool, ContextRegistry, ContextSearchTool, default_context_sources
from tinyagent.core.contextfs import refresh_contextfs
from tinyagent.core.contracts import ApprovalHandler, Executor, LocalExecutor, ModelProvider, PolicyEngine, Profile, Tool
from tinyagent.core.events import EventSink, json_safe
from tinyagent.core.extensions import Extension, ExtensionHost
from tinyagent.core.hook_runner import HookErrorPolicy, HookRunner
from tinyagent.core.hooks import TinyHook
from tinyagent.core.index import SearchCodeTool, WorkspaceIndexManager
from tinyagent.core.model_stream import complete_model_call
from tinyagent.core.models import model_spec
from tinyagent.core.observations import Observation, extract_observations
from tinyagent.core.output import (
    capture_final_diff,
    write_context_report_artifact,
    write_final_text,
    write_json_artifact,
    write_model_http_request_artifact,
    write_model_request_artifacts,
    write_model_response_artifact,
    write_run_outputs,
)
from tinyagent.core.progress import ProgressGuard
from tinyagent.core.resources import LoadedResources
from tinyagent.core.run_control import CancelToken, RunCancelled
from tinyagent.core.skills import SkillRegistry, default_skill_sources
from tinyagent.core.skills.tools import ListSkillsTool, LoadSkillTool
from tinyagent.core.state import (
    ApprovalGrant,
    ApprovalMode,
    ApprovalRequest,
    ApprovalResolution,
    FinishDecision,
    Message,
    ModelResponse,
    PolicyDecision,
    RunBudgets,
    RunState,
    ToolCall,
    ToolResult,
    ToolStep,
)
from tinyagent.core.tools.builtins.shell import shell_preflight
from tinyagent.core.workspace import SandboxModeInput, WorkspaceMode, prepare_workspace
from tinyagent.core.workspace_delta import WorkspaceDeltaObserver

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
        approval_handler: ApprovalHandler | None = None,
        executor: Executor | None = None,
        budgets: RunBudgets | None = None,
        stream: bool = False,
        event_sink: EventSink | None = None,
        approval_mode: ApprovalMode = "yolo",
        workspace_mode: WorkspaceMode = "auto",
        sandbox_mode: SandboxModeInput = "none",
        hooks: Sequence[TinyHook] = (),
        extensions: Sequence[Extension] = (),
        resources: LoadedResources | None = None,
        hook_error_policy: HookErrorPolicy = "fail",
        progress_guard: ProgressGuard | None = None,
        workspace_delta_observer: WorkspaceDeltaObserver | None = None,
        workspace_index_manager: WorkspaceIndexManager | None = None,
    ) -> None:
        loaded_extensions = tuple(resources.extensions) if resources is not None else ()
        extension_host = ExtensionHost((*loaded_extensions, *tuple(extensions)))
        base_skill_sources = default_skill_sources() if resources is None or resources.skill_sources is None else resources.skill_sources
        skill_registry = SkillRegistry((*base_skill_sources, *extension_host.skills()))
        self.skill_registry = skill_registry
        resource_context_sources = resources.context_sources if resources is not None else ()
        self.context_registry = ContextRegistry((*default_context_sources(skill_registry), *resource_context_sources, *extension_host.context_sources()))
        self.model = model
        self.profile = profile
        base_tools = {tool.name: tool for tool in (*tools, *extension_host.tools())}
        if _uses_default_tool_surface(base_tools):
            base_tools["list_skills"] = ListSkillsTool(skill_registry)
            base_tools["load_skill"] = LoadSkillTool(skill_registry)
            base_tools["context_search"] = ContextSearchTool(self.context_registry)
            base_tools["context_read"] = ContextReadTool(self.context_registry)
            base_tools["search_code"] = SearchCodeTool()
        self.tools = base_tools
        self.policy = policy
        self.approval_handler = approval_handler
        self.executor = executor or LocalExecutor()
        self.budgets = budgets or RunBudgets()
        self.stream = stream
        self.event_sink = event_sink
        self.approval_mode = approval_mode
        self.workspace_mode = workspace_mode
        self.sandbox_mode = sandbox_mode
        self.hooks = (*tuple(hooks), *extension_host.hooks())
        self.hook_error_policy = hook_error_policy
        self.hook_runner = HookRunner(self.hooks, error_policy=hook_error_policy)
        self.progress_guard = progress_guard or ProgressGuard()
        self.workspace_delta_observer = workspace_delta_observer or WorkspaceDeltaObserver()
        self.workspace_index_manager = workspace_index_manager

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
        sandbox_mode: SandboxModeInput | None = None,
        parent_run_id: str | None = None,
        parent_event_id: str | None = None,
        branch_name: str | None = None,
        prior_messages: Sequence[Message] = (),
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
            prior_messages=prior_messages,
        )
        state.workspace_envelope = prepared_workspace.envelope
        state.skill_registry = self.skill_registry
        state.workspace_index = self.workspace_index_manager or WorkspaceIndexManager.for_workspace(prepared_workspace.workspace.root)
        state.context_registry = self.context_registry
        state.model_spec = model_spec(self.model).to_json_dict()
        state.approval_mode = approval_mode or self.approval_mode
        state.status = "running"
        if cancel_token is not None:
            state.cancel_token = cancel_token
        use_stream = self.stream if stream is None else stream
        state.stream_sink = event_sink if event_sink is not None else self.event_sink

        try:
            self._run_hooks(state, "on_run_start", state)
            profile_metadata = _profile_trace_metadata(self.profile, state, self.tools)
            model_metadata = dict(state.model_spec)
            state.emit(
                "run.started",
                {
                    "task": task,
                    "provider": model_metadata.get("provider"),
                    "model": model_metadata.get("model"),
                    "protocol": model_metadata.get("protocol"),
                    "adapter": model_metadata.get("adapter"),
                    "capabilities": model_metadata.get("capabilities"),
                    **profile_metadata,
                    "workspace_root": str(state.workspace.root),
                    "original_workspace_root": (
                        str(state.workspace_envelope.original_root)
                        if state.workspace_envelope
                        else str(Path(workspace).expanduser().resolve())
                    ),
                    "budgets": state.budgets.to_json_dict(),
                    "stream": use_stream,
                    "workspace_mode": (
                        state.workspace_envelope.mode if state.workspace_envelope else (workspace_mode or self.workspace_mode)
                    ),
                    "approval_mode": state.approval_mode,
                    "sandbox_mode": (
                        state.workspace_envelope.sandbox_mode if state.workspace_envelope else (sandbox_mode or self.sandbox_mode)
                    ),
                    "sandbox_backend": state.workspace_envelope.sandbox_backend if state.workspace_envelope else "none",
                    "network_mode": state.workspace_envelope.network_mode if state.workspace_envelope else "deny",
                    "sandbox_enforced": bool(state.workspace_envelope.sandbox_enforced) if state.workspace_envelope else False,
                    "parent_run_id": state.parent_run_id,
                    "parent_event_id": state.parent_event_id,
                    "branch_name": state.branch_name,
                },
            )
            if state.prior_messages:
                state.prior_context_artifact = write_json_artifact(
                    state,
                    "prior-context.json",
                    {
                        "messages": [
                            {"role": message.role, "content": json_safe(message.content), "meta": json_safe(message.meta)}
                            for message in state.prior_messages
                        ],
                    },
                    kind="prior_context",
                )
            self._emit_workspace_boundary(state, prepared_workspace.worktree_created)
            if "shell" in self.tools:
                state.shell_preflight = shell_preflight(state)
                state.emit("shell.preflight.completed", state.shell_preflight)
            index_path = refresh_contextfs(state)
            state.emit("contextfs.index.updated", {"path": index_path, "phase": "startup"})
            self._sync_workspace_index(state, mode="fast", paths=None, phase="startup")
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
            spec = model_spec(self.model)
            capabilities = spec.capabilities
            if visible_tools and not capabilities.supports_tools:
                state.emit(
                    "model.call.failed",
                    {
                        "provider": self.model.name,
                        "reason": "model provider does not support tools",
                        "capabilities": capabilities.to_json_dict(),
                    },
                    visibility="user",
                )
                state.fail("Model provider does not support tools.")
                return
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
                    "model_spec": spec.to_json_dict(),
                    "token_estimate": built_context.token_estimate,
                    "model_call_token_estimate": actual_token_estimate,
                    "tool_schema_tokens": estimate_tools_tokens(visible_tools),
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
                budget=_context_budget(self.profile, state, capabilities),
                model_capabilities=capabilities,
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
                visibility="user",
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

        progress = self.progress_guard.before_tool_call(state, call)
        if not progress.allow:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=progress.reason,
                ok=False,
                data={"blocked": True, "progress_blocked": True, "failure_kind": "progress_blocked"},
                failure_kind="progress_blocked",
                summary=progress.reason,
                content_preview=progress.reason,
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
            state.raise_if_cancelled()
            if decision.kind == "deny":
                self._record_policy_decision(state, call, decision)
        if not decision.allowed:
            data = _blocked_result_data(decision)
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=decision.reason or "Policy denied tool call.",
                ok=False,
                data=data,
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
        state.emit("workspace.delta.started", {"tool_call_id": call.id, "tool": call.name})
        before_delta = self.workspace_delta_observer.snapshot(state)
        state.emit(
            "tool.execution.started",
            {"tool_call_id": call.id, "tool_execution_id": tool_execution_id, "tool": call.name},
            visibility="user",
        )
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
        after_delta = self.workspace_delta_observer.snapshot(state)
        workspace_delta = self.workspace_delta_observer.diff(state, before_delta, after_delta, call)
        if workspace_delta.mutated:
            result.metadata["workspace_delta"] = workspace_delta.to_json_dict()
            result.data["workspace_delta"] = workspace_delta.to_json_dict()
        else:
            result.metadata["workspace_delta"] = workspace_delta.to_json_dict()
        self._append_tool_step(state, call, result)
        self._record_tool_result(state, call, result)
        if workspace_delta.mutated:
            self._record_workspace_delta(state, call, result, workspace_delta)
        else:
            state.emit("workspace.delta.completed", {"tool_call_id": call.id, "tool": call.name, "mutated": False, "ok": result.ok})
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

    def _record_workspace_delta(self, state: RunState, call: ToolCall, result: ToolResult, delta) -> None:
        payload = {"tool_call_id": call.id, "tool": call.name, "ok": result.ok, "failure_kind": result.failure_kind, **delta.to_json_dict()}
        state.emit("workspace.delta.completed", payload)
        self._sync_workspace_index(state, mode="overlay-fast", paths=delta.paths, phase="workspace_delta", tool_call_id=call.id)
        state.emit(
            "workspace.mutation.detected",
            payload,
            visibility="user",
            artifact_refs=[delta.diff_artifact] if delta.diff_artifact else [],
        )
        if delta.diff_artifact:
            state.emit("diff.snapshot", {"tool_call_id": call.id, "path": delta.diff_artifact, "paths": list(delta.paths)})
        for path in delta.paths:
            state.emit("file.changed", {"tool_call_id": call.id, "tool": call.name, "path": path})
            state.observations.append(
                Observation(
                    kind="file_changed",
                    subject=path,
                    summary=f"{path} changed by {call.name}.",
                    refs=(delta.diff_artifact,) if delta.diff_artifact else (),
                    data={"path": path, "tool_call_id": call.id, "source": "workspace_delta"},
                )
            )
            state.emit("observation.recorded", state.observations[-1].to_json_dict(), artifact_refs=list(state.observations[-1].refs))
        state.observations.append(
            Observation(
                kind="diff_seen",
                subject=call.id,
                summary=f"Workspace delta captured after {call.name}.",
                refs=(delta.diff_artifact,) if delta.diff_artifact else (),
                data={"paths": list(delta.paths), "tool_call_id": call.id, "source": "workspace_delta"},
            )
        )
        state.emit("observation.recorded", state.observations[-1].to_json_dict(), artifact_refs=list(state.observations[-1].refs))

    def _sync_workspace_index(
        self,
        state: RunState,
        *,
        mode: str,
        paths: Sequence[str] | None,
        phase: str,
        tool_call_id: str | None = None,
    ) -> None:
        if not isinstance(state.workspace_index, WorkspaceIndexManager):
            return
        status = state.workspace_index.status()
        payload: dict[str, Any] = {"mode": mode, "backend": status.backend, "phase": phase}
        if tool_call_id is not None:
            payload["tool_call_id"] = tool_call_id
        if paths is not None:
            payload["path_count"] = len(paths)
        state.emit("index.sync.started", payload)
        try:
            sync = state.workspace_index.sync(root=state.workspace.root, paths=paths, mode=mode)  # type: ignore[arg-type]
            state.emit(
                "index.sync.completed" if not sync.error else "index.sync.failed",
                {
                    **payload,
                    "mode": sync.mode,
                    "backend": sync.backend,
                    "synced_file_count": sync.synced_file_count,
                    "stale_file_count": sync.stale_file_count,
                    "duration_ms": sync.duration_ms,
                    "error": sync.error,
                },
            )
        except Exception as exc:
            state.emit("index.sync.failed", {**payload, "error": str(exc)})

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
        for key in ("capability", "source", "recoverability"):
            value = result.data.get(key)
            if value:
                payload[key] = value
        if result.read_hints:
            payload["read_hints"] = result.read_hints
        state.emit("tool.execution.completed" if result.ok else "tool.execution.failed", payload, visibility="user")

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
            observation.data.setdefault("tool_call_id", call.id)
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
                "capability": decision.permission,
                "source": "policy",
                "recoverability": "request_approval" if decision.kind == "needs_approval" else "choose_alternative",
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
                state.finish_step("failed", data={"approval_id": approval.approval_id, "reason": str(exc)})
            else:
                if resolution.decision == "cancelled":
                    state.finish_step("cancelled", data={"approval_id": approval.approval_id, "decision": resolution.decision})
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
        return PolicyDecision.deny(
            resolution.reason or f"approval {resolution.decision}",
            matched_rule=decision.matched_rule,
            permission=decision.permission,
        )

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
                visibility="user",
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
                visibility="user",
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
        if call.name not in {"apply_patch", "str_replace_edit", "write_file", "shell"}:
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
        write_final_text(state)
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
                state.emit("artifact.materialized", {"path": path, "kind": "run_output"}, visibility="user")
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
            "sandbox_backend": state.workspace_envelope.sandbox_backend if state.workspace_envelope else "none",
            "network_mode": state.workspace_envelope.network_mode if state.workspace_envelope else "deny",
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
        return self.hook_runner.before_finish(state, response, decision)

    def _run_hooks(self, state: RunState, method_name: str, *args) -> None:
        self.hook_runner.call_void(state, method_name, *args)

    def _on_context(self, state: RunState, built_context: BuiltContext) -> BuiltContext:
        return self.hook_runner.on_context(state, built_context)

    def _after_model_response(self, state: RunState, response: ModelResponse) -> ModelResponse:
        return self.hook_runner.after_model_response(state, response)

    def _before_model_call(self, state: RunState, messages: list[Message], tools: list[Tool]) -> tuple[list[Message], list[Tool]]:
        return self.hook_runner.before_model_call(state, messages, tools)

    def _before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolCall | ToolResult | None:
        return self.hook_runner.before_tool_call(state, call, decision)

    def _after_tool_result(self, state: RunState, result: ToolResult) -> ToolResult:
        return self.hook_runner.after_tool_result(state, result)


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


def _blocked_result_data(decision: PolicyDecision) -> dict[str, object]:
    capability = decision.permission or "unknown"
    return {
        "blocked": True,
        "failure_kind": "policy_denied",
        "capability": capability,
        "source": "policy",
        "recoverability": "request_approval" if decision.kind == "needs_approval" else "choose_alternative",
        "permission": capability,
        "matched_rule": decision.matched_rule,
    }


def _context_budget(profile: Profile, state: RunState, capabilities=None) -> int:
    config = getattr(profile, "context_config", None)
    budget = getattr(config, "effective_compact_at_tokens", None)
    capability_budget = capabilities.input_budget_tokens if capabilities is not None else None
    if isinstance(budget, int):
        return min(budget, capability_budget) if isinstance(capability_budget, int) else budget
    if isinstance(capability_budget, int):
        return capability_budget
    return state.context_token_estimate


def _profile_trace_metadata(profile: Profile, state: RunState, tools: Mapping[str, Tool]) -> dict[str, Any]:
    visible_tools = [tool.name for tool in profile.visible_tools(state, tools)]
    system_prompt = profile.system_prompt()
    return {
        "profile": profile.name,
        "profile_variant": str(getattr(profile, "profile_variant", "default")),
        "system_prompt_hash": hashlib.sha256(system_prompt.encode()).hexdigest()[:12],
        "profile_visible_tools": visible_tools,
        "context_policy": str(getattr(profile, "context_policy_name", "dynamic-v1")),
        "skill_policy": str(getattr(profile, "skill_policy_name", "default-v1")),
        "tool_surface": str(getattr(profile, "tool_surface_name", "default")),
    }


def _uses_default_tool_surface(tools: Mapping[str, Tool]) -> bool:
    return _DEFAULT_TOOL_SENTINELS.issubset(tools)


_DEFAULT_TOOL_SENTINELS = frozenset({"shell", "apply_patch", "str_replace_edit", "write_file", "read_file", "list_files"})


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
