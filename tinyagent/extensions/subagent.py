"""Subagent extension: an `agent` tool that delegates a subtask to a bounded child run.

The child is a full kernel run in the same workspace with its own run directory,
linked to the parent through parent_run_id/parent_event_id and the existing
child_run.* events. Children are read-only (plan session mode) unless the model
asks for edits, never prompt for approvals (approval-required actions are denied
with a reason the child must report), and cannot spawn children of their own.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from uuid import uuid4

from tinyagent.core.context_sources import ContextSource
from tinyagent.core.contracts import ModelProvider, PolicyEngine, Tool, ToolRuntime
from tinyagent.core.extensions import ExtensionInfo
from tinyagent.core.hooks import TinyHook
from tinyagent.core.kernel import Kernel
from tinyagent.core.output import record_child_summary
from tinyagent.core.profiles import profile_for
from tinyagent.core.skills import SkillSource
from tinyagent.core.state import RunBudgets, RunState, ToolCall, ToolResult
from tinyagent.core.tools import default_tools

KernelFactory = Callable[[str, RunBudgets], Kernel]

_MIN_CHILD_RUN_SECONDS = 30


@dataclass(frozen=True)
class SubagentLimits:
    max_model_calls: int = 24
    max_tool_calls: int = 60
    max_run_seconds: int = 300


class AgentTool:
    name = "agent"
    runtime = ToolRuntime(parallel_safe=False, mutates_workspace=True, requires_shell=True)

    def __init__(
        self,
        kernel_factory: KernelFactory,
        *,
        profiles: Sequence[str] = ("tiny-pi", "tiny-coder"),
        default_profile: str = "tiny-pi",
        limits: SubagentLimits | None = None,
    ) -> None:
        self.kernel_factory = kernel_factory
        self.profiles = tuple(profiles)
        self.default_profile = default_profile
        self.limits = limits or SubagentLimits()
        self.schema = {
            "name": self.name,
            "description": (
                "Delegate a self-contained subtask to a bounded subagent that works in this same workspace "
                "and returns a final report. Use it when you do not need the subtask's full detail in your "
                "own context: broad exploration ('find every caller of X and report file:line for each'), "
                "independent verification, or an isolated implementation step. The subagent starts with no "
                "memory of this conversation, so the task must include all relevant paths, constraints, and "
                "the exact report you expect back. Subagents are read-only unless allow_edits is true, never "
                "ask for approval (blocked actions are reported instead), and cannot spawn subagents."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Self-contained instructions plus the report you expect back.",
                    },
                    "profile": {
                        "type": "string",
                        "enum": list(self.profiles),
                        "description": f"Subagent profile (default {self.default_profile}).",
                    },
                    "allow_edits": {
                        "type": "boolean",
                        "description": "Allow workspace mutations. When false the subagent runs in read-only plan mode.",
                    },
                },
                "required": ["task"],
            },
        }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        task = str(call.args.get("task") or "").strip()
        if not task:
            return _refusal(self.name, call, "task is required", failure_kind="invalid_tool_args")
        if state.parent_run_id:
            return _refusal(self.name, call, "Subagents cannot spawn subagents; do this subtask yourself.")
        profile_name = str(call.args.get("profile") or self.default_profile).strip().lower()
        if profile_name not in self.profiles:
            return _refusal(
                self.name,
                call,
                f"Unknown subagent profile: {profile_name}. Available: {', '.join(self.profiles)}.",
                failure_kind="invalid_tool_args",
            )
        allow_edits = bool(call.args.get("allow_edits", False)) and state.session_mode != "plan"

        budgets = self._child_budgets(state)
        child_run_id = f"run_sub_{uuid4().hex[:12]}"
        kernel = self.kernel_factory(profile_name, budgets)
        started = state.emit(
            "child_run.started",
            {
                "child_run_id": child_run_id,
                "tool_call_id": call.id,
                "profile": profile_name,
                "read_only": not allow_edits,
                "task_preview": task[:200],
                "budgets": budgets.to_json_dict(),
            },
            visibility="user",
        )
        envelope = state.workspace_envelope
        child = kernel.run(
            task,
            workspace=state.workspace.root,
            run_id=child_run_id,
            cancel_token=state.cancel_token,
            workspace_mode="current",
            approval_mode="yolo",
            session_mode="normal" if allow_edits else "plan",
            sandbox_mode=envelope.sandbox_mode if envelope else "none",
            parent_run_id=state.run_id,
            parent_event_id=started.id,
        )
        summary_artifact = record_child_summary(state, child)
        ok = bool(child.done and not child.failed and not child.cancelled)
        output = child.final_output or child.failure_reason or f"Child run {child.status} without final output."
        data: dict[str, object] = {
            "child_run_id": child_run_id,
            "status": child.status,
            "profile": profile_name,
            "read_only": not allow_edits,
            "output_dir": str(child.output_dir),
            "summary_artifact": summary_artifact,
            "model_calls": child.model_call_count,
            "tool_calls": child.tool_call_count,
        }
        if child.cancelled:
            data["cancelled"] = True
            data["reason"] = child.cancel_reason or "cancelled"
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=output,
            ok=ok,
            data=data,
            failure_kind=None if ok else "child_run_failed",
            summary=f"subagent {child.status} ({profile_name}, {child.model_call_count} model calls, {child.tool_call_count} tool calls)",
            content_preview=output[:200],
        )

    def _child_budgets(self, state: RunState) -> RunBudgets:
        remaining_seconds = max(int(state.budgets.max_run_seconds - state.elapsed_seconds()), _MIN_CHILD_RUN_SECONDS)
        return replace(
            state.budgets,
            max_model_calls=self.limits.max_model_calls,
            max_tool_calls=self.limits.max_tool_calls,
            max_run_seconds=min(self.limits.max_run_seconds, remaining_seconds),
        )


class SubagentExtension:
    name = "subagent"

    def __init__(
        self,
        kernel_factory: KernelFactory,
        *,
        profiles: Sequence[str] = ("tiny-pi", "tiny-coder"),
        default_profile: str = "tiny-pi",
        limits: SubagentLimits | None = None,
    ) -> None:
        self._tool = AgentTool(kernel_factory, profiles=profiles, default_profile=default_profile, limits=limits)

    def hooks(self) -> Sequence[TinyHook]:
        return ()

    def tools(self) -> Sequence[Tool]:
        return (self._tool,)

    def skills(self) -> Sequence[SkillSource]:
        return ()

    def context_sources(self) -> Sequence[ContextSource]:
        return ()

    def info(self) -> ExtensionInfo:
        return ExtensionInfo(
            name=self.name,
            description="agent tool that runs bounded child runs in the same workspace",
            permissions=("spawn_child_runs",),
        )


def _refusal(tool_name: str, call: ToolCall, reason: str, *, failure_kind: str = "invalid_tool_args") -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        call_id=call.id,
        output=reason,
        ok=False,
        data={"blocked": True, "failure_kind": failure_kind},
        failure_kind=failure_kind,
        summary=reason,
        content_preview=reason,
    )


def subagent_extension(
    *,
    model: ModelProvider,
    policy: PolicyEngine,
    profiles: Sequence[str] = ("tiny-pi", "tiny-coder"),
    default_profile: str = "tiny-pi",
    limits: SubagentLimits | None = None,
) -> SubagentExtension:
    """Default wiring: child kernels share the parent's model and policy engine.

    Children run yolo with policy enforced and approval-required actions denied,
    so they only ever do what policy already allows. They are built without
    extensions, which makes recursion structurally impossible.
    """

    def factory(profile_name: str, budgets: RunBudgets) -> Kernel:
        return Kernel(
            model=model,
            profile=profile_for(profile_name),
            tools=default_tools(),
            policy=policy,
            budgets=budgets,
            approval_mode="yolo",
            enforce_policy_in_yolo=True,
            deny_yolo_approvals=True,
            workspace_mode="current",
        )

    return SubagentExtension(factory, profiles=profiles, default_profile=default_profile, limits=limits)
