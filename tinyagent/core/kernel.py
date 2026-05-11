"""Minimal tinyagent kernel loop."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from tinyagent.core.approval import record_policy_decision, resolve_approval
from tinyagent.core.context import estimate_messages_tokens, estimate_tools_tokens
from tinyagent.core.context_lifecycle import build_context, compact_context, profile_should_compact, refresh_contextfs_if_enabled
from tinyagent.core.context_sources import ContextReadTool, ContextRegistry, ContextSearchTool, default_context_sources
from tinyagent.core.contracts import (
    ApprovalHandler,
    Executor,
    LocalExecutor,
    ModelProvider,
    PolicyEngine,
    Profile,
    ProfileRuntimeCapabilities,
    Tool,
)
from tinyagent.core.events import EventSink, json_safe
from tinyagent.core.extensions import Extension, ExtensionHost
from tinyagent.core.finalizer import finalize_artifacts, finalize_run
from tinyagent.core.hook_runner import HookErrorPolicy, HookRunner
from tinyagent.core.hooks import TinyHook
from tinyagent.core.index import SearchCodeTool, WorkspaceIndexManager
from tinyagent.core.model_recording import record_model_tool_calls
from tinyagent.core.model_stream import complete_model_call
from tinyagent.core.models import model_spec
from tinyagent.core.observations import Observation
from tinyagent.core.output import (
    write_context_report_artifact,
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
    ApprovalMode,
    FinishDecision,
    Message,
    ModelResponse,
    PolicyDecision,
    RunBudgets,
    RunState,
    ToolCall,
    ToolResult,
)
from tinyagent.core.tool_recording import (
    append_tool_step,
    record_tool_blocked,
    record_tool_result_event,
)
from tinyagent.core.tools.builtins.shell import shell_preflight
from tinyagent.core.workspace import SandboxModeInput, WorkspaceMode, prepare_workspace
from tinyagent.core.workspace_delta import WorkspaceDeltaObserver


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
        runtime = _profile_runtime_capabilities(profile)
        loaded_extensions = tuple(resources.extensions) if resources is not None and runtime.extensions else ()
        explicit_extensions = tuple(extensions) if runtime.extensions else ()
        extension_host = ExtensionHost((*loaded_extensions, *explicit_extensions))
        if runtime.skills:
            base_skill_sources = (
                default_skill_sources()
                if resources is None or resources.skill_sources is None
                else resources.skill_sources
            )
        else:
            base_skill_sources = ()
        skill_registry = SkillRegistry((*base_skill_sources, *extension_host.skills()))
        self.skill_registry = skill_registry
        resource_context_sources = resources.context_sources if resources is not None and runtime.dynamic_context else ()
        context_sources = (
            (*default_context_sources(skill_registry), *resource_context_sources, *extension_host.context_sources())
            if runtime.dynamic_context
            else ()
        )
        self.context_registry = ContextRegistry(context_sources)
        self.model = model
        self.profile = profile
        base_tools = {tool.name: tool for tool in (*tools, *extension_host.tools())}
        if runtime.tool_names is not None:
            base_tools = {name: tool for name, tool in base_tools.items() if name in runtime.tool_names}
        if _uses_default_tool_surface(base_tools):
            if runtime.skills:
                base_tools["list_skills"] = ListSkillsTool(skill_registry)
                base_tools["load_skill"] = LoadSkillTool(skill_registry)
            if runtime.dynamic_context:
                base_tools["context_search"] = ContextSearchTool(self.context_registry)
                base_tools["context_read"] = ContextReadTool(self.context_registry)
            if runtime.workspace_index:
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
        self.runtime_capabilities = runtime

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
        state.workspace_index = (
            self.workspace_index_manager or WorkspaceIndexManager.for_workspace(prepared_workspace.workspace.root)
            if self.runtime_capabilities.workspace_index
            else None
        )
        state.context_registry = self.context_registry
        state.model_spec = model_spec(self.model).to_json_dict()
        state.approval_mode = approval_mode or self.approval_mode
        state.status = "running"
        if cancel_token is not None:
            state.cancel_token = cancel_token
        use_stream = self.stream if stream is None else stream
        state.stream_sink = event_sink if event_sink is not None else self.event_sink

        try:
            self.hook_runner.call_void(state, "on_run_start", state)
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
            self._refresh_contextfs(state, {"phase": "startup"})
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
            finalize_artifacts(state, contextfs_enabled=self.runtime_capabilities.contextfs)
            state.finish_turn()
            finalize_run(state, contextfs_enabled=self.runtime_capabilities.contextfs)
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
            built_context = build_context(
                state,
                self.profile,
                visible_tools,
                contextfs_enabled=self.runtime_capabilities.contextfs,
            )
            if profile_should_compact(self.profile, state):
                compact_context(
                    state,
                    self.profile,
                    before_compact=lambda: self.hook_runner.call_void(state, "before_compact", state),
                )
                built_context = build_context(
                    state,
                    self.profile,
                    visible_tools,
                    contextfs_enabled=self.runtime_capabilities.contextfs,
                )
            built_context = self.hook_runner.on_context(state, built_context)
            messages = built_context.messages
            messages, visible_tools = self.hook_runner.before_model_call(state, messages, visible_tools)
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
                response = self.hook_runner.after_model_response(state, response)
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
            tool_recording_error = record_model_tool_calls(
                state,
                response.tool_calls,
                provider=self.model.name,
                model_call_id=model_call_id,
                model_call_index=model_call_index,
            )
            if tool_recording_error is not None:
                state.finish_step("failed", data={"provider": self.model.name, "reason": tool_recording_error})
                state.fail(tool_recording_error)
                return
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
            self._record_blocked_tool_call(state, call, result)
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
            self._record_blocked_tool_call(state, call, result)
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
            self._record_blocked_tool_call(state, call, result)
            return

        try:
            decision = self.policy.evaluate(call, state)
        except Exception as exc:
            decision = PolicyDecision.deny(f"Policy engine error: {exc}")
            record_policy_decision(state, call, decision)
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
            self._record_blocked_tool_call(state, call, result)
            state.fail(decision.reason)
            return

        record_policy_decision(state, call, decision)
        hook_result = self.hook_runner.before_tool_call(state, call, decision)
        if isinstance(hook_result, ToolResult):
            result = hook_result if hook_result.call_id else replace(hook_result, call_id=call.id)
            self._record_blocked_tool_call(state, call, result)
            return
        if isinstance(hook_result, ToolCall):
            call = hook_result
            try:
                decision = self.policy.evaluate(call, state)
            except Exception as exc:
                decision = PolicyDecision.deny(f"Policy engine error after hook mutation: {exc}")
            record_policy_decision(state, call, decision)
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
                self._record_blocked_tool_call(state, call, result)
                return
        if decision.kind == "needs_approval":
            decision = resolve_approval(state, decision, approval_handler=self.approval_handler)
            state.raise_if_cancelled()
            if decision.kind == "deny":
                record_policy_decision(state, call, decision)
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
            self._record_blocked_tool_call(state, call, result)
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
        try:
            result = self.hook_runner.after_tool_result(state, result)
        except Exception as exc:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=str(exc),
                ok=False,
                data={"hook_failed": True, "error_type": type(exc).__name__},
                failure_kind="unknown",
                summary=str(exc),
                content_preview=str(exc),
            )
        if not result.call_id:
            result = replace(result, call_id=call.id)
        after_delta = self.workspace_delta_observer.snapshot(state)
        workspace_delta = self.workspace_delta_observer.diff(state, before_delta, after_delta, call)
        if workspace_delta.mutated:
            result.metadata["workspace_delta"] = workspace_delta.to_json_dict()
            result.data["workspace_delta"] = workspace_delta.to_json_dict()
        else:
            result.metadata["workspace_delta"] = workspace_delta.to_json_dict()
        append_tool_step(state, call, result)
        record_tool_result_event(state, call, result)
        if workspace_delta.mutated:
            self._record_workspace_delta(state, call, result, workspace_delta)
        else:
            state.emit("workspace.delta.completed", {"tool_call_id": call.id, "tool": call.name, "mutated": False, "ok": result.ok})
        self._refresh_contextfs(state, {"tool_call_id": call.id})
        if result.data.get("cancelled"):
            state.finish_step("cancelled", data={"reason": result.data.get("reason") or "cancelled"})
        elif result.ok:
            state.finish_step("completed", data={"tool_call_id": call.id, "tool": call.name})
        else:
            state.finish_step("failed", data={"tool_call_id": call.id, "tool": call.name})
        self._record_mutation_event(state, "workspace.mutation.completed", call, ok=result.ok)
        if result.data.get("cancelled"):
            state.request_cancel(str(result.data.get("reason") or state.cancel_reason or "cancelled"))

    def _record_blocked_tool_call(self, state: RunState, call: ToolCall, result: ToolResult) -> None:
        append_tool_step(state, call, result)
        record_tool_result_event(state, call, result)
        record_tool_blocked(state, call, result.output)
        self._refresh_contextfs(state, {"tool_call_id": call.id})

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

    def _refresh_contextfs(self, state: RunState, data: Mapping[str, Any] | None = None) -> None:
        refresh_contextfs_if_enabled(state, contextfs_enabled=self.runtime_capabilities.contextfs, data=data)

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

    def _before_finish(self, state: RunState, response: ModelResponse) -> FinishDecision:
        before_finish = getattr(self.profile, "before_finish", None)
        decision = before_finish(state, response) if callable(before_finish) else FinishDecision.allowed()
        return self.hook_runner.before_finish(state, response, decision)

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


def _profile_runtime_capabilities(profile: Profile) -> ProfileRuntimeCapabilities:
    runtime = getattr(profile, "runtime_capabilities", None)
    if isinstance(runtime, ProfileRuntimeCapabilities):
        return runtime
    return ProfileRuntimeCapabilities()


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
