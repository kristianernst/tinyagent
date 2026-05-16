"""Context state and build result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from tinyagent.core.state import Message
from tinyagent.core.token_utils import estimate_tokens


@dataclass(frozen=True)
class ContextConfig:
    project_instruction_max_tokens: int = 8_192
    max_recent_tool_tokens: int = 12_000
    compact_after_tool_steps: int = 16
    model_context_window: int = 128_000
    compact_at_tokens: int = 96_000
    reserve_output_tokens: int = 8_000
    shell: str | None = None

    @property
    def effective_compact_at_tokens(self) -> int:
        return min(self.compact_at_tokens, max(1, self.model_context_window - self.reserve_output_tokens))

    def with_model_budget(self, *, context_window: int, max_output_tokens: int) -> ContextConfig:
        return ContextConfig(
            project_instruction_max_tokens=self.project_instruction_max_tokens,
            max_recent_tool_tokens=self.max_recent_tool_tokens,
            compact_after_tool_steps=self.compact_after_tool_steps,
            model_context_window=context_window,
            compact_at_tokens=min(self.compact_at_tokens, max(1, context_window - max_output_tokens)),
            reserve_output_tokens=max_output_tokens,
            shell=self.shell,
        )


@dataclass(frozen=True)
class ContextPlan:
    mode: Literal["explore", "edit", "debug", "verify", "summarize", "finish"] = "explore"
    pinned_observation_kinds: frozenset[str] = frozenset()
    recent_tail_budget: int | None = None
    reason: str = "default context plan"

    def to_json_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "pinned_observation_kinds": sorted(self.pinned_observation_kinds),
            "recent_tail_budget": self.recent_tail_budget,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    description: str = ""


@dataclass(frozen=True)
class ContextItem:
    id: str
    role: str
    text: str
    source: str
    priority: int
    token_estimate: int
    stable: bool = False
    tags: tuple[str, ...] = ()
    expires_after_steps: int | None = None


@dataclass(frozen=True)
class ContextExclusion:
    item_id: str
    reason: Literal["budget", "expired", "lower_priority", "duplicate", "profile_filtered"]
    token_estimate: int


@dataclass
class ContextState:
    objective: str = ""
    constraints: list[str] = field(default_factory=list)
    files_seen: dict[str, str] = field(default_factory=dict)
    files_changed: dict[str, str] = field(default_factory=dict)
    commands_run: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    open_issues: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    compaction_count: int = 0


@dataclass(frozen=True)
class ProjectInstructions:
    content: str = ""
    files: tuple[str, ...] = ()
    truncated: bool = False

    @property
    def token_estimate(self) -> int:
        return estimate_tokens(self.content)


@dataclass(frozen=True)
class BuiltContext:
    messages: list[Message]
    token_estimate: int
    static_context_tokens: int
    tool_context_tokens: int
    project_instruction_tokens: int
    artifacts: list[ArtifactRef] = field(default_factory=list)
    included: list[ContextItem] = field(default_factory=list)
    excluded: list[ContextExclusion] = field(default_factory=list)
    contextfs_index_path: str | None = None
    context_plan: ContextPlan | None = None
