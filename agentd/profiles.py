"""Default profile implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from agentd.context import BuiltContext, ContextBuilder, ContextConfig, compact_state
from agentd.contracts import Tool
from agentd.state import Message, RunState

PROFILE_ROOT = Path(__file__).resolve().parents[1] / "profiles"


class ApexCoderProfile:
    name = "apex-coder"
    DEFAULT_VISIBLE_TOOL_NAMES = ("shell", "apply_patch")

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
        return ContextBuilder(system_prompt=self.system_prompt(), config=self.context_config).build(state)

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return self.build_context(state).messages

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        return [all_tools[name] for name in self.visible_tool_names if name in all_tools]

    def should_continue(self, state: RunState) -> bool:
        return not state.done

    def should_finish(self, state: RunState) -> bool:
        return False

    def should_compact(self, state: RunState) -> bool:
        new_steps = len(state.tool_steps) - state.context_checkpoint_tool_step_count
        if new_steps <= 0:
            return False
        if self.context_config.compact_after_tool_steps > 0 and new_steps >= self.context_config.compact_after_tool_steps:
            return True
        return state.context_token_estimate >= self.context_config.effective_compact_at_tokens

    def compact(self, state: RunState) -> None:
        compact_state(state, self.context_config)
