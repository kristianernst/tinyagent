"""State objects shared across the tinyagent kernel."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentd.events import Event, utc_now


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


@dataclass(frozen=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"call_{uuid4().hex}")


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    output: str
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    finish: bool = False


@dataclass(frozen=True)
class ModelResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


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
    tool_results: list[ToolResult] = field(default_factory=list)
    turn_count: int = 0
    tool_call_count: int = 0
    done: bool = False
    failed: bool = False
    failure_reason: str | None = None
    summary: str = ""
    final_diff: str = ""

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
        resolved_run_id = run_id or f"run_{uuid4().hex}"
        resolved_output_dir = output_dir or resolved_workspace.root / ".tinyagent" / "runs" / resolved_run_id
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
