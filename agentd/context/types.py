"""Context state and build result types."""

from __future__ import annotations

from dataclasses import dataclass, field

from agentd.state import Message


@dataclass(frozen=True)
class ContextConfig:
    project_instruction_max_chars: int = 32 * 1024
    max_recent_tool_tokens: int = 12_000
    compact_after_tool_steps: int = 16
    model_context_window: int = 128_000
    compact_at_tokens: int = 96_000
    reserve_output_tokens: int = 8_000
    shell: str | None = None

    @property
    def effective_compact_at_tokens(self) -> int:
        return min(self.compact_at_tokens, max(1, self.model_context_window - self.reserve_output_tokens))


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    description: str = ""


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
    def chars(self) -> int:
        return len(self.content)


@dataclass(frozen=True)
class BuiltContext:
    messages: list[Message]
    token_estimate: int
    static_context_chars: int
    tool_context_chars: int
    project_instruction_chars: int
    artifacts: list[ArtifactRef] = field(default_factory=list)
