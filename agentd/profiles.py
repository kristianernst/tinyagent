"""Default profile implementations."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from agentd.context import BuiltContext, ContextBuilder, ContextConfig, ContextPlan, compact_state
from agentd.context.checkpoint import is_test_command_text
from agentd.contracts import Tool
from agentd.state import FinishDecision, Message, ModelResponse, RunState, ToolStep

PROFILE_ROOT = Path(__file__).resolve().parents[1] / "profiles"


class ApexCoderProfile:
    name = "apex-coder"
    DEFAULT_VISIBLE_TOOL_NAMES = ("read_file", "search_repo", "apply_patch", "shell")

    def __init__(
        self,
        *,
        system_prompt_path: Path | None = None,
        recent_results: int = 8,
        context_config: ContextConfig | None = None,
        recent_tool_token_budget: int | None = None,
        visible_tool_names: Sequence[str] | None = None,
    ) -> None:
        self.system_prompt_path = system_prompt_path or PROFILE_ROOT / "apex-coder" / "system.md"
        self.recent_results = recent_results
        self.visible_tool_names = tuple(visible_tool_names) if visible_tool_names is not None else self.DEFAULT_VISIBLE_TOOL_NAMES
        self.context_config = context_config or ContextConfig()
        if recent_tool_token_budget is not None:
            self.context_config = replace(self.context_config, max_recent_tool_tokens=recent_tool_token_budget)
        self._system_prompt = self._load_system_prompt()

    def system_prompt(self) -> str:
        return self._system_prompt

    def _load_system_prompt(self) -> str:
        if self.system_prompt_path.exists():
            return self.system_prompt_path.read_text()
        return (
            "You are tinyagent's default coding profile. Use shell for inspection, search, tests, and git. "
            "Use apply_patch for edits. Finish by returning assistant content when done."
        )

    def build_context(self, state: RunState) -> BuiltContext:
        return ContextBuilder(system_prompt=self.system_prompt(), config=self.context_config).build(
            state,
            plan=self.plan_next_context(state),
        )

    def plan_next_context(self, state: RunState) -> ContextPlan:
        kinds = [observation.kind for observation in state.observations]
        edited_index = _latest_index(state.tool_steps, _is_successful_edit)
        verification_index = _latest_index(state.tool_steps, _is_successful_verification)
        diff_index = _latest_index(state.tool_steps, _is_diff_inspection)
        latest_failed = _latest_index(state.tool_steps, lambda step: not step.result.ok)
        if any(kind in {"test_failure", "command_failed"} for kind in kinds) or latest_failed is not None:
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
        return [all_tools[name] for name in self.visible_tool_names if name in all_tools]

    def should_continue(self, state: RunState) -> bool:
        return not state.done

    def should_finish(self, state: RunState) -> bool:
        return False

    def before_finish(self, state: RunState, response: ModelResponse) -> FinishDecision:
        content = response.content or ""
        edited_index = _latest_index(state.tool_steps, _is_successful_edit)
        if edited_index is not None:
            if _requires_git_diff(state):
                diff_index = _latest_index(state.tool_steps, _is_diff_inspection)
                if diff_index is None or diff_index < edited_index:
                    return FinishDecision.blocked(
                        "finish blocked: inspect git diff after edits",
                        "Before finalizing, inspect git diff after the latest edit.",
                    )
            else:
                file_inspection_index = _latest_index(
                    state.tool_steps,
                    lambda step: _is_changed_file_inspection(step, state.tool_steps[edited_index]),
                )
                if (file_inspection_index is None or file_inspection_index < edited_index) and not _mentions_diff_limitation(content):
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
        compact_state(state, self.context_config)


def _latest_index(steps: list[ToolStep], predicate) -> int | None:
    for index in range(len(steps) - 1, -1, -1):
        if predicate(steps[index]):
            return index
    return None


def _is_successful_edit(step: ToolStep) -> bool:
    return step.call.name == "apply_patch" and step.result.ok


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
    paths = [str(path).lower() for path in (edit_step.result.metadata.get("paths") or edit_step.result.data.get("paths") or [])]
    if step.call.name == "read_file":
        read_path = str(step.result.data.get("path") or step.call.args.get("path") or "").lower()
        return bool(read_path and read_path in paths)
    if step.call.name != "shell":
        return False
    cmd = str(step.call.args.get("cmd", "")).lower()
    if not any(token in cmd for token in ("cat ", "sed ", "rg ", "head ", "tail ", "python", "awk ")):
        return False
    return any(path in cmd for path in paths)


def _is_successful_verification(step: ToolStep) -> bool:
    if step.call.name != "shell" or not step.result.ok:
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
    return re.search(r"\b(tests?|checks?|verification)\s+(passed|pass|green|succeeded)", content.lower()) is not None
