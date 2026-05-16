"""Default profile implementations."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from tinyagent.core.context import (
    BuiltContext,
    ContextBuilder,
    ContextConfig,
    ContextItem,
    ContextPlan,
    compact_state,
    estimate_messages_tokens,
    render_environment_context,
    render_project_instructions,
    render_recent_tool_steps,
)
from tinyagent.core.context.builder import render_conversation_history, render_finish_gate_messages
from tinyagent.core.context.checkpoint import is_test_command_text, is_verification_command_text
from tinyagent.core.context.instructions import load_project_instructions
from tinyagent.core.contracts import Tool, tool_runtime
from tinyagent.core.profile_catalog import (
    DEFAULT_PROFILE_NAMES,
    DEFAULT_RUNTIME_CAPABILITIES,
    TINY_PI_PROFILE_NAMES,
    TINY_PI_RUNTIME_CAPABILITIES,
)
from tinyagent.core.state import FinishDecision, Message, ModelResponse, RunState, ToolStep
from tinyagent.core.token_utils import estimate_tokens

PROFILE_ROOT = Path(__file__).resolve().parents[1] / "profiles"

DEFAULT_CODER_SYSTEM_PROMPT = (
    "You are tinyagent's default coding profile. Use shell for inspection, search, tests, and git. "
    "Use apply_patch for edits. Inspect enough context to act, then implement; do not re-read files already shown "
    "unless they changed, were truncated, or a failure requires it. After a successful apply_patch, trust the patch "
    "result and move to verification or diff inspection instead of re-reading the same file. Finish by returning "
    "assistant content when done."
)


class ApexCoderProfile:
    name = "tiny-coder"
    profile_variant = "default"
    context_policy_name = "dynamic-v1"
    skill_policy_name = "default-v1"
    tool_surface_name = "default"
    DEFAULT_VISIBLE_TOOL_NAMES = (
        "read_file",
        "context_search",
        "context_read",
        "search_code",
        "list_skills",
        "load_skill",
        "mcp_search_tools",
        "mcp_load_tool",
        "mcp_call",
        "mcp_read_resource",
        "lsp_symbols",
        "lsp_definition",
        "lsp_references",
        "lsp_diagnostics",
        "todo_read",
        "todo_write",
        "apply_patch",
        "shell",
    )
    runtime_capabilities = DEFAULT_RUNTIME_CAPABILITIES

    def __init__(
        self,
        *,
        system_prompt_path: Path | None = None,
        recent_results: int = 8,
        context_config: ContextConfig | None = None,
        recent_tool_token_budget: int | None = None,
        visible_tool_names: Sequence[str] | None = None,
    ) -> None:
        self.system_prompt_path = system_prompt_path or PROFILE_ROOT / "tiny-coder" / "system.md"
        self.recent_results = recent_results
        self.visible_tool_names = tuple(visible_tool_names) if visible_tool_names is not None else self.DEFAULT_VISIBLE_TOOL_NAMES
        self.context_config = context_config or ContextConfig(compact_after_tool_steps=64)
        if recent_tool_token_budget is not None:
            self.context_config = replace(self.context_config, max_recent_tool_tokens=recent_tool_token_budget)
        self._system_prompt = self._load_system_prompt()

    def system_prompt(self) -> str:
        return self._system_prompt

    def _load_system_prompt(self) -> str:
        if self.system_prompt_path.exists():
            return self.system_prompt_path.read_text()
        return DEFAULT_CODER_SYSTEM_PROMPT

    def build_context(self, state: RunState, *, visible_tools: Sequence[Tool] | None = None) -> BuiltContext:
        visible_tool_objects = tuple(visible_tools or ())
        visible_tool_names = [tool.name for tool in visible_tool_objects] if visible_tools is not None else self.visible_tool_names
        return ContextBuilder(
            system_prompt=_system_prompt_with_parallel_guidance(self.system_prompt(), state, visible_tool_objects),
            config=self._context_config_for_state(state),
        ).build(
            state,
            plan=self.plan_next_context(state),
            visible_tool_names=visible_tool_names,
        )

    def plan_next_context(self, state: RunState) -> ContextPlan:
        edited_index = _latest_index(state.tool_steps, _is_successful_mutation)
        verification_index = _latest_index(state.tool_steps, _is_successful_verification)
        diff_index = _latest_index(state.tool_steps, _is_diff_inspection)
        latest_failed = _latest_index(state.tool_steps, lambda step: not step.result.ok)
        latest_recovery = max((index for index in (edited_index, verification_index, diff_index) if index is not None), default=None)
        active_failure = latest_failed is not None and (latest_recovery is None or latest_failed > latest_recovery)
        if active_failure:
            return ContextPlan(
                mode="debug",
                pinned_observation_kinds=frozenset({"test_failure", "command_failed", "file_changed", "policy_block"}),
                reason="recent failure needs debugging evidence",
            )
        if edited_index is not None and (verification_index is None or verification_index < edited_index):
            return ContextPlan(
                mode="verify",
                pinned_observation_kinds=frozenset({"patch_applied", "file_changed", "diff_seen", "verification"}),
                reason="latest edit still needs verification evidence",
            )
        if edited_index is not None and (diff_index is not None or verification_index is not None):
            return ContextPlan(
                mode="finish",
                pinned_observation_kinds=frozenset({"file_changed", "diff_seen", "verification", "policy_block"}),
                reason="finish candidate needs change and verification evidence",
            )
        if state.tool_steps:
            return ContextPlan(
                mode="edit",
                pinned_observation_kinds=frozenset({"search_result", "diff_seen"}),
                reason="recent inspection can guide edits",
            )
        return ContextPlan(mode="explore", reason="initial context discovery")

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return self.build_context(state).messages

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        tool_names = _visible_tool_names_for_state(state, self.visible_tool_names)
        return [all_tools[name] for name in tool_names if name in all_tools]

    def should_continue(self, state: RunState) -> bool:
        return not state.done

    def should_finish(self, state: RunState) -> bool:
        return False

    def before_finish(self, state: RunState, response: ModelResponse) -> FinishDecision:
        content = response.content or ""
        edited_index = _latest_index(state.tool_steps, _is_successful_mutation)
        if edited_index is not None:
            if _requires_git_diff(state):
                diff_index = _latest_index(state.tool_steps, _is_diff_inspection)
                if diff_index is None or diff_index <= edited_index:
                    return FinishDecision.blocked(
                        "finish blocked: inspect git diff after edits",
                        "Before finalizing, inspect git diff after the latest edit.",
                    )
            else:
                file_inspection_index = _latest_index(
                    state.tool_steps,
                    lambda step: _is_changed_file_inspection(step, state.tool_steps[edited_index]),
                )
                if (file_inspection_index is None or file_inspection_index <= edited_index) and not _mentions_diff_limitation(content):
                    return FinishDecision.blocked(
                        "finish blocked: inspect changed files after edits",
                        "Before finalizing in this non-git workspace, inspect changed files "
                        "or explain that git diff is unavailable.",
                    )
            verification_index = _latest_index(state.tool_steps, _is_successful_verification)
            if verification_index is None or verification_index < edited_index:
                if not _mentions_verification_limitation(content):
                    return FinishDecision.blocked(
                        "finish blocked: run verification after edits or explain why it cannot run",
                        "Before finalizing, run the smallest relevant verification command, or explain exactly why it cannot run.",
                    )

        last_step = state.tool_steps[-1] if state.tool_steps else None
        if last_step is not None and not last_step.result.ok and not _mentions_failure(content):
            return FinishDecision.blocked(
                "finish blocked: last tool failed and final answer did not report it",
                "The last tool failed. Report the failure/current state before finalizing, or continue investigating.",
            )

        blocked_step = _latest_index(
            state.tool_steps,
            lambda step: (step.result.failure_kind or step.result.data.get("failure_kind")) in {"policy_denied", "sandbox_blocked"},
        )
        if blocked_step is not None and not _mentions_limitation(content):
            return FinishDecision.blocked(
                "finish blocked: policy/sandbox limitation was not reported",
                "A policy or sandbox limitation occurred. Mention it explicitly or request approval before finalizing.",
            )

        if _claims_tests_passed(content) and _latest_index(state.tool_steps, _is_successful_verification) is None:
            return FinishDecision.blocked(
                "finish blocked: final answer claims tests passed without passing verification evidence",
                "Do not claim tests passed unless a passing verification command exists in the trace.",
            )
        return FinishDecision.allowed()

    def should_compact(self, state: RunState) -> bool:
        new_steps = len(state.tool_steps) - state.context_checkpoint_tool_step_count
        if new_steps <= 0:
            return False
        if self.context_config.compact_after_tool_steps > 0 and new_steps >= self.context_config.compact_after_tool_steps:
            return True
        return state.context_token_estimate >= self.context_config.effective_compact_at_tokens

    def compact(self, state: RunState) -> None:
        compact_state(state, self._context_config_for_state(state))

    def _context_config_for_state(self, state: RunState) -> ContextConfig:
        capabilities = (state.model_spec or {}).get("capabilities")
        if not isinstance(capabilities, dict):
            return self.context_config
        context_window = capabilities.get("context_window")
        max_output_tokens = capabilities.get("max_output_tokens")
        if not isinstance(context_window, int) or not isinstance(max_output_tokens, int):
            return self.context_config
        return self.context_config.with_model_budget(context_window=context_window, max_output_tokens=max_output_tokens)


class TinyPiProfile:
    name = "tiny-pi"
    profile_variant = "minimal"
    context_policy_name = "pi-v1"
    skill_policy_name = "none"
    tool_surface_name = "pi-minimal"
    DEFAULT_VISIBLE_TOOL_NAMES = ("read_file", "apply_patch", "shell")
    runtime_capabilities = TINY_PI_RUNTIME_CAPABILITIES

    def __init__(
        self,
        *,
        recent_results: int = 4,
        context_config: ContextConfig | None = None,
        visible_tool_names: Sequence[str] | None = None,
    ) -> None:
        self.recent_results = recent_results
        self.visible_tool_names = tuple(visible_tool_names) if visible_tool_names is not None else self.DEFAULT_VISIBLE_TOOL_NAMES
        self.context_config = context_config or ContextConfig(
            project_instruction_max_tokens=2_000,
            max_recent_tool_tokens=2_000,
            compact_after_tool_steps=12,
            compact_at_tokens=48_000,
            reserve_output_tokens=4_000,
        )
        self._system_prompt = (
            "You are tinyagent, a small coding agent working in this workspace. "
            "Inspect files before editing when needed. Use shell for commands and verification. "
            "Use the edit tool for file changes. Keep responses concise. Respect policy and sandbox messages. "
            "Do not claim tests or checks passed unless you ran them and they passed. "
            "Finish with what changed and what you verified."
        )

    def system_prompt(self) -> str:
        return self._system_prompt

    def build_context(self, state: RunState, *, visible_tools: Sequence[Tool] | None = None) -> BuiltContext:
        config = self._context_config_for_state(state)
        visible_tool_objects = tuple(visible_tools or ())
        visible_tool_names = [tool.name for tool in visible_tool_objects] if visible_tools is not None else self.visible_tool_names
        system_prompt = _system_prompt_with_parallel_guidance(self.system_prompt(), state, visible_tool_objects)
        instructions = load_project_instructions(state.workspace.root, config)
        recent = render_recent_tool_steps(
            state,
            config,
            ContextPlan(mode="edit" if state.tool_steps else "explore", reason="tiny-pi lean context"),
            visible_tool_names=visible_tool_names,
        )
        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=render_environment_context(state, config)),
            Message(role="user", content=render_project_instructions(instructions)),
            Message(role="user", content=f"Task:\n{state.task}"),
            Message(role="user", content=recent),
        ]
        conversation = render_conversation_history(state, visible_tool_names=frozenset(visible_tool_names))
        if conversation:
            messages.insert(3, Message(role="user", content=conversation))
        finish_gate = render_finish_gate_messages(state)
        if finish_gate:
            messages.append(Message(role="user", content=finish_gate))
        included = [
            _context_item("system:profile", system_prompt, "system_prompt", 1000, stable=True),
            _context_item("environment:current", str(messages[1].content), "environment", 850, stable=True),
            _context_item("project:instructions", str(messages[2].content), "project_instructions", 800, stable=True),
            *([_context_item("conversation:history", conversation, "conversation_history", 925, stable=True)] if conversation else []),
            _context_item("task:current", f"Task:\n{state.task}", "task", 950, stable=True),
            _context_item("recent_tools:preview", recent, "recent_tool_steps", 600, stable=True),
            *([_context_item("finish_gate:messages", finish_gate, "finish_gate", 780)] if finish_gate else []),
        ]
        return BuiltContext(
            messages=messages,
            token_estimate=estimate_messages_tokens(messages),
            static_context_tokens=sum(estimate_tokens(str(message.content)) for message in messages),
            tool_context_tokens=estimate_tokens(recent),
            project_instruction_tokens=instructions.token_estimate,
            included=included,
            context_plan=ContextPlan(mode="explore", reason="tiny-pi lean context"),
        )

    def plan_next_context(self, state: RunState) -> ContextPlan:
        return ContextPlan(mode="edit" if state.tool_steps else "explore", reason="tiny-pi lean context")

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return self.build_context(state).messages

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        tool_names = _edit_style_visible_tool_names(state, self.visible_tool_names, default=self.DEFAULT_VISIBLE_TOOL_NAMES)
        return [all_tools[name] for name in tool_names if name in all_tools]

    def should_continue(self, state: RunState) -> bool:
        return not state.done

    def should_finish(self, state: RunState) -> bool:
        return False

    def before_finish(self, state: RunState, response: ModelResponse) -> FinishDecision:
        content = response.content or ""
        edited_index = _latest_index(state.tool_steps, _is_successful_mutation)
        if _claims_tests_passed(content):
            verification_index = _latest_index(state.tool_steps, _is_successful_verification)
            if verification_index is None or (edited_index is not None and verification_index < edited_index):
                return FinishDecision.blocked(
                    "finish blocked: final answer claims tests passed without current passing verification evidence",
                    "Do not claim tests passed unless a relevant passing verification command exists after the latest edit.",
                )
        failed_verification_index = _latest_index(state.tool_steps, _is_failed_verification)
        if failed_verification_index is not None:
            next_success = _latest_index(state.tool_steps, _is_successful_verification)
            if (next_success is None or next_success < failed_verification_index) and not _mentions_failure(content):
                return FinishDecision.blocked(
                    "finish blocked: failed verification was not reported",
                    "Report the failed verification or continue investigating.",
                )
        last_step = state.tool_steps[-1] if state.tool_steps else None
        if last_step is not None and not last_step.result.ok and not _mentions_failure(content):
            return FinishDecision.blocked(
                "finish blocked: last tool failed and final answer did not report it",
                "The last tool failed. Report the failure/current state before finalizing, or continue investigating.",
            )
        blocked_index = _latest_index(
            state.tool_steps,
            lambda step: (step.result.failure_kind or step.result.data.get("failure_kind")) in {"policy_denied", "sandbox_blocked"},
        )
        if blocked_index is not None and not _mentions_limitation(content):
            return FinishDecision.blocked(
                "finish blocked: policy/sandbox limitation was not reported",
                "A policy or sandbox limitation occurred. Mention it explicitly or request approval before finalizing.",
            )
        return FinishDecision.allowed()

    def should_compact(self, state: RunState) -> bool:
        new_steps = len(state.tool_steps) - state.context_checkpoint_tool_step_count
        return new_steps > 0 and (
            new_steps >= self.context_config.compact_after_tool_steps
            or state.context_token_estimate >= self.context_config.effective_compact_at_tokens
        )

    def compact(self, state: RunState) -> None:
        compact_state(state, self._context_config_for_state(state))

    def _context_config_for_state(self, state: RunState) -> ContextConfig:
        capabilities = (state.model_spec or {}).get("capabilities")
        if not isinstance(capabilities, dict):
            return self.context_config
        context_window = capabilities.get("context_window")
        max_output_tokens = capabilities.get("max_output_tokens")
        if not isinstance(context_window, int) or not isinstance(max_output_tokens, int):
            return self.context_config
        return self.context_config.with_model_budget(context_window=context_window, max_output_tokens=max_output_tokens)


def profile_for(
    name: str | None = None,
    *,
    visible_tool_names: Sequence[str] | None = None,
    context_config: ContextConfig | None = None,
):
    normalized = (name or "tiny-coder").strip().lower()
    if normalized in DEFAULT_PROFILE_NAMES:
        return ApexCoderProfile(visible_tool_names=visible_tool_names, context_config=context_config)
    if normalized in TINY_PI_PROFILE_NAMES:
        return TinyPiProfile(visible_tool_names=visible_tool_names, context_config=context_config)
    raise ValueError(f"Unknown profile: {name}")


def _system_prompt_with_parallel_guidance(system_prompt: str, state: RunState, visible_tools: Sequence[Tool]) -> str:
    guidance = _parallel_exploration_guidance(state, visible_tools)
    return f"{system_prompt.rstrip()}\n\n{guidance}" if guidance else system_prompt


def _parallel_exploration_guidance(state: RunState, visible_tools: Sequence[Tool]) -> str:
    capabilities = (state.model_spec or {}).get("capabilities")
    if not isinstance(capabilities, dict) or capabilities.get("supports_parallel_tool_calls") is not True:
        return ""
    tool_names = _parallel_batchable_tool_names(visible_tools)
    if not tool_names:
        return ""
    return "\n".join(
        [
            "Parallel tool use:",
            "- Batch independent read-only calls in one model response when all inputs are already known.",
            f"- Batchable tools in this context: {', '.join(tool_names)}.",
            "- Do not batch mutating tools, shell commands, network tools, or calls whose arguments depend on a previous result.",
            "- After edits, verify with tests or diff evidence instead of re-reading unchanged files.",
        ]
    )


def _parallel_batchable_tool_names(visible_tools: Sequence[Tool]) -> tuple[str, ...]:
    names: list[str] = []
    seen: set[str] = set()
    for tool in visible_tools:
        runtime = tool_runtime(tool)
        if (
            not runtime.parallel_safe
            or runtime.mutates_workspace
            or runtime.requires_shell
            or runtime.requires_network
            or runtime.lock_key is not None
        ):
            continue
        if tool.name in seen:
            continue
        seen.add(tool.name)
        names.append(tool.name)
    return tuple(names)


def _latest_index(steps: list[ToolStep], predicate) -> int | None:
    for index in range(len(steps) - 1, -1, -1):
        if predicate(steps[index]):
            return index
    return None


def _visible_tool_names_for_state(state: RunState, configured: Sequence[str]) -> tuple[str, ...]:
    return _edit_style_visible_tool_names(state, configured, default=ApexCoderProfile.DEFAULT_VISIBLE_TOOL_NAMES)


def _edit_style_visible_tool_names(state: RunState, configured: Sequence[str], *, default: Sequence[str]) -> tuple[str, ...]:
    if tuple(configured) != tuple(default):
        return tuple(configured)
    edit_style = str((state.model_spec or {}).get("edit_style") or "apply_patch")
    match edit_style:
        case "str_replace":
            return _replace_default_edit_tool(default, "str_replace_edit")
        case "whole_file":
            return _replace_default_edit_tool(default, "write_file")
        case _:
            return tuple(default)


def _replace_default_edit_tool(default: Sequence[str], edit_tool: str) -> tuple[str, ...]:
    return tuple(edit_tool if name == "apply_patch" else name for name in default)


def _context_item(item_id: str, text: str, source: str, priority: int, *, stable: bool = False) -> ContextItem:
    return ContextItem(
        id=item_id,
        role="user",
        text=text,
        source=source,
        priority=priority,
        token_estimate=estimate_tokens(text),
        stable=stable,
    )


def _is_successful_mutation(step: ToolStep) -> bool:
    delta = step.result.metadata.get("workspace_delta") or step.result.data.get("workspace_delta") or {}
    if isinstance(delta, dict) and delta.get("mutated"):
        return True
    if not step.result.ok:
        return False
    return step.call.name in {"apply_patch", "str_replace_edit", "write_file"} and step.result.ok


def _is_diff_inspection(step: ToolStep) -> bool:
    if step.call.name != "shell" or not step.result.ok:
        return False
    cmd = str(step.call.args.get("cmd", "")).lower()
    return any(pattern in cmd for pattern in ("git diff", "git show"))


def _requires_git_diff(state: RunState) -> bool:
    envelope = state.workspace_envelope
    if envelope is not None:
        return envelope.dirty_state_before.is_git_repo
    return (state.workspace.root / ".git").exists()


def _is_changed_file_inspection(step: ToolStep, edit_step: ToolStep) -> bool:
    if not step.result.ok:
        return False
    paths = _changed_paths_for_step(edit_step)
    if step.call.name == "read_file":
        read_path = str(step.result.data.get("path") or step.call.args.get("path") or "").lower()
        return bool(read_path and read_path in paths)
    if step.call.name != "shell":
        return False
    cmd = str(step.call.args.get("cmd", "")).lower()
    if not any(token in cmd for token in ("cat ", "sed ", "rg ", "head ", "tail ", "python", "awk ")):
        return False
    return any(path in cmd for path in paths)


def _changed_paths_for_step(step: ToolStep) -> list[str]:
    paths = step.result.metadata.get("paths") or step.result.data.get("paths") or []
    if not paths:
        delta = step.result.metadata.get("workspace_delta") or step.result.data.get("workspace_delta") or {}
        if isinstance(delta, dict):
            paths = delta.get("paths") or []
    return [str(path).lower() for path in paths]


def _is_successful_verification(step: ToolStep) -> bool:
    if step.call.name != "shell" or not step.result.ok:
        return False
    cmd = str(step.call.args.get("cmd", ""))
    return is_verification_command_text(cmd)


def _is_failed_verification(step: ToolStep) -> bool:
    if step.call.name != "shell" or step.result.ok:
        return False
    cmd = str(step.call.args.get("cmd", ""))
    return is_test_command_text(cmd) or any(
        token in cmd.lower() for token in ("-m pytest", "-m unittest", "npm test", "cargo test", "go test", "ruff", "mypy")
    )


def _mentions_verification_limitation(content: str) -> bool:
    text = content.lower()
    return any(phrase in text for phrase in ("could not run", "unable to run", "did not run", "not run", "verification unavailable"))


def _mentions_diff_limitation(content: str) -> bool:
    text = content.lower()
    return "git diff" in text and any(phrase in text for phrase in ("could not", "unable", "unavailable", "not a git", "non-git"))


def _mentions_failure(content: str) -> bool:
    text = content.lower()
    return any(word in text for word in ("failed", "failure", "error", "blocked", "denied", "could not"))


def _mentions_limitation(content: str) -> bool:
    text = content.lower()
    return any(word in text for word in ("policy", "sandbox", "blocked", "denied", "approval", "permission"))


def _claims_tests_passed(content: str) -> bool:
    text = content.lower()
    return any(
        re.search(pattern, text) is not None
        for pattern in (
            r"\b(?:tests?|test suite|checks?|verification)\s+(?:are\s+|is\s+)?(?:passing|passed|pass|green|succeeded)",
            r"\b(?:passing|passed|green|succeeded)\s+(?:tests?|test suite|checks?|verification)",
            r"\b(?:all|the)\s+(?:tests?|checks?)\s+(?:are\s+|were\s+)?(?:passing|passed|green)",
        )
    )
