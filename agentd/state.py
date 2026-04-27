"""State objects shared across the tinyagent kernel."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agentd.events import Event, utc_now

if TYPE_CHECKING:
    from agentd.context import ContextState


def _default_context_state() -> ContextState:
    from agentd.context import ContextState

    return ContextState()


@dataclass(frozen=True)
class RunBudgets:
    max_turns: int = 30
    max_tool_calls: int = 100
    max_shell_timeout_seconds: int = 60
    max_run_seconds: int = 600
    max_command_output_chars_visible: int = 12_000

    def to_json_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class Workspace:
    root: Path

    def resolved_root(self) -> Path:
        return self.root.expanduser().resolve()

    def resolve_path(self, path: str | Path = ".") -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return candidate.resolve()

    def contains(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            return False
        return True


@dataclass(frozen=True)
class Message:
    role: str
    content: Any = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"call_{uuid4().hex}")


@dataclass(frozen=True)
class ToolResult:
    """A tool observation. data must stay small; large payloads belong in artifacts."""

    tool_name: str
    output: str
    call_id: str = ""
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolStep:
    call: ToolCall
    result: ToolResult


@dataclass
class ModelResponse:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tool_calls = tuple(self.tool_calls)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    redacted: bool = False

    @classmethod
    def allow(cls, reason: str = "allowed") -> PolicyDecision:
        return cls(allowed=True, reason=reason)

    @classmethod
    def deny(cls, reason: str) -> PolicyDecision:
        return cls(allowed=False, reason=reason)


@dataclass
class RunState:
    run_id: str
    task: str
    workspace: Workspace
    output_dir: Path
    budgets: RunBudgets = field(default_factory=RunBudgets)
    started_at: datetime = field(default_factory=utc_now)
    events: list[Event] = field(default_factory=list)
    tool_steps: list[ToolStep] = field(default_factory=list)
    turn_count: int = 0
    tool_call_count: int = 0
    done: bool = False
    failed: bool = False
    failure_reason: str | None = None
    summary: str = ""
    final_diff: str = ""
    shell_preflight: dict[str, Any] = field(default_factory=dict)
    persist_events: bool = True
    context_state: ContextState = field(default_factory=_default_context_state)
    context_checkpoint: str = ""
    context_checkpoint_artifact: str = ""
    context_checkpoint_tool_step_count: int = 0
    context_token_estimate: int = 0
    compaction_count: int = 0

    @property
    def tool_results(self) -> list[ToolResult]:
        return [step.result for step in self.tool_steps]

    @classmethod
    def create(
        cls,
        task: str,
        workspace: Workspace,
        *,
        budgets: RunBudgets | None = None,
        run_id: str | None = None,
        output_dir: Path | None = None,
    ) -> RunState:
        resolved_workspace = Workspace(workspace.resolved_root())
        if not resolved_workspace.root.exists() or not resolved_workspace.root.is_dir():
            raise ValueError(f"Workspace does not exist or is not a directory: {resolved_workspace.root}")
        resolved_run_id = run_id or f"run_{uuid4().hex}"
        resolved_output_dir = (
            output_dir.expanduser().resolve()
            if output_dir
            else resolved_workspace.root / ".tinyagent" / "runs" / resolved_run_id
        )
        return cls(
            run_id=resolved_run_id,
            task=task,
            workspace=resolved_workspace,
            output_dir=resolved_output_dir,
            budgets=budgets or RunBudgets(),
        )

    def add_event(self, event_type: str, data: dict[str, Any] | None = None, parent_event_id: str | None = None) -> Event:
        event = Event(
            run_id=self.run_id,
            type=event_type,
            data=data or {},
            parent_event_id=parent_event_id,
        )
        self.events.append(event)
        if self.persist_events:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with (self.output_dir / "events.jsonl").open("a") as file:
                file.write(json.dumps(event.to_json_dict(), sort_keys=True) + "\n")
        return event

    def elapsed_seconds(self) -> float:
        return (utc_now() - self.started_at).total_seconds()

    def fail(self, reason: str) -> None:
        if self.done:
            return
        self.done = True
        self.failed = True
        self.failure_reason = reason
        self.add_event("RunFailed", {"reason": reason})

    def finish(self, summary: str = "") -> None:
        if self.done:
            return
        self.done = True
        self.summary = summary or self.summary
        self.add_event("RunFinished", {"summary": self.summary})
