"""State objects shared across the tinyagent kernel."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from tinyagent.core.events import Event, EventDurability, EventSink, EventVisibility, small_event_data, utc_now
from tinyagent.core.run_control import CancelToken, RunCancelled
from tinyagent.core.workspace import Workspace, WorkspaceEnvelope

if TYPE_CHECKING:
    from tinyagent.core.context import ContextState
    from tinyagent.core.observations import Observation
    from tinyagent.core.transcript import Transcript


def _default_context_state() -> ContextState:
    from tinyagent.core.context import ContextState

    return ContextState()


def _default_transcript() -> Transcript:
    from tinyagent.core.transcript import Transcript

    return Transcript()


@dataclass(frozen=True)
class RunBudgets:
    max_model_calls: int = 30
    max_tool_calls: int = 100
    max_shell_timeout_seconds: int = 60
    max_model_timeout_seconds: int = 180
    max_model_idle_timeout_seconds: int = 60
    max_run_seconds: int = 600
    max_tool_output_tokens_visible: int = 3_000

    def to_json_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None, *, base: RunBudgets | None = None) -> RunBudgets:
        values = asdict(base or cls())
        if not data:
            return cls(**values)
        unknown = sorted(set(data) - set(values))
        if unknown:
            raise ValueError(f"Unknown run budget fields: {', '.join(unknown)}")
        for key, value in data.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"Run budget {key} must be an integer")
            if value < 0:
                raise ValueError(f"Run budget {key} must be non-negative")
            values[key] = value
        return cls(**values)


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
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class ToolResult:
    """A tool observation. data must stay small; large payloads belong in artifacts."""

    tool_name: str
    output: str
    call_id: str = ""
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)
    exit_code: int | None = field(default=None, compare=False)
    duration_ms: int = field(default=0, compare=False)
    summary: str = field(default="", compare=False)
    content_preview: str = field(default="", compare=False)
    artifact_path: str | None = field(default=None, compare=False)
    truncated: bool = field(default=False, compare=False)
    failure_kind: str | None = field(default=None, compare=False)
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)
    read_hints: list[str] = field(default_factory=list, compare=False)


@dataclass(frozen=True)
class ToolStep:
    call: ToolCall
    result: ToolResult


@dataclass(frozen=True)
class ModelRequestContext:
    """Normalized provider-facing run context.

    Providers should use this instead of the full RunState. It contains only the
    small state needed to shape model requests and provider-native tool history.
    """

    run_id: str
    tool_steps: tuple[ToolStep, ...] = ()
    context_checkpoint_tool_step_count: int = 0
    conversation_state: ModelConversationState | None = None

    @classmethod
    def from_run_state(cls, state: RunState) -> ModelRequestContext:
        return cls(
            run_id=state.run_id,
            tool_steps=tuple(state.tool_steps),
            context_checkpoint_tool_step_count=state.context_checkpoint_tool_step_count,
            conversation_state=state.model_conversation_state,
        )

    def tool_steps_since_checkpoint(self) -> tuple[ToolStep, ...]:
        return self.tool_steps[self.context_checkpoint_tool_step_count :]


@dataclass
class ModelConversationState:
    provider: str
    adapter: str
    mode: str = "stateless_replay"
    response_id: str | None = None
    conversation_id: str | None = None
    prompt_cache_key: str | None = None
    opaque: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "provider": self.provider,
            "adapter": self.adapter,
            "mode": self.mode,
        }
        if self.response_id:
            data["response_id"] = self.response_id
        if self.conversation_id:
            data["conversation_id"] = self.conversation_id
        if self.prompt_cache_key:
            data["prompt_cache_key"] = self.prompt_cache_key
        if self.opaque:
            data["opaque"] = small_event_data(self.opaque)
        return data


@dataclass
class ModelResponse:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    conversation_state: ModelConversationState | None = None

    def __post_init__(self) -> None:
        self.tool_calls = tuple(self.tool_calls)


@dataclass(frozen=True)
class FinishDecision:
    allow: bool
    reason: str = ""
    injected_message: str | None = None

    @classmethod
    def allowed(cls, reason: str = "allowed") -> FinishDecision:
        return cls(True, reason)

    @classmethod
    def blocked(cls, reason: str, injected_message: str | None = None) -> FinishDecision:
        return cls(False, reason, injected_message)


ApprovalDecision = Literal["approved", "denied", "cancelled", "expired"]
ApprovalMode = Literal["never", "on-request", "yolo"]
SessionMode = Literal["normal", "plan"]
ApprovalScope = Literal["once", "run"]
PolicyDecisionKind = Literal["allow", "deny", "needs_approval"]
StepKind = Literal["model_call", "tool_execution", "approval_wait", "artifact_finalization"]
TerminalStatus = Literal["completed", "failed", "cancelled", "interrupted", "timed_out"]


@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    run_id: str
    turn_id: str | None
    step_id: str | None
    action_kind: Literal["shell", "patch", "network", "workspace_escape", "dirty_mutation", "unknown"]
    tool_name: str
    cwd: str
    args_preview: str
    command: str | None
    risk: Literal["low", "medium", "high"]
    scope_options: tuple[ApprovalScope, ...] = ("once", "run")

    def grant_key(self) -> str:
        return f"{self.action_kind}:{self.tool_name}:{self.command or self.args_preview}"

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalResolution:
    approval_id: str
    decision: ApprovalDecision
    scope: ApprovalScope | None = None
    reason: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalGrant:
    approval_id: str
    grant_key: str
    scope: ApprovalScope
    created_at: datetime = field(default_factory=utc_now)

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat().replace("+00:00", "Z")
        return data


@dataclass(frozen=True)
class PolicyDecision:
    kind: PolicyDecisionKind
    reason: str = ""
    redacted: bool = False
    approval: ApprovalRequest | None = None
    matched_rule: str | None = None
    permission: str = "unknown"
    suggested_approval: dict[str, Any] | None = None

    @property
    def allowed(self) -> bool:
        return self.kind == "allow"

    @classmethod
    def allow(cls, reason: str = "allowed", *, matched_rule: str | None = None, permission: str = "unknown") -> PolicyDecision:
        return cls(kind="allow", reason=reason, matched_rule=matched_rule, permission=permission)

    @classmethod
    def deny(cls, reason: str, *, matched_rule: str | None = None, permission: str = "unknown") -> PolicyDecision:
        return cls(kind="deny", reason=reason, matched_rule=matched_rule, permission=permission)

    @classmethod
    def needs_approval(
        cls,
        reason: str,
        approval: ApprovalRequest,
        *,
        matched_rule: str | None = None,
        permission: str = "unknown",
    ) -> PolicyDecision:
        return cls(
            kind="needs_approval",
            reason=reason,
            approval=approval,
            matched_rule=matched_rule,
            permission=permission,
            suggested_approval=approval.to_json_dict(),
        )


@dataclass
class RunState:
    run_id: str
    task: str
    workspace: Workspace
    output_dir: Path
    budgets: RunBudgets = field(default_factory=RunBudgets)
    started_at: datetime = field(default_factory=utc_now)
    events: list[Event] = field(default_factory=list)
    seq: int = 0
    tool_steps: list[ToolStep] = field(default_factory=list)
    turn_count: int = 0
    model_call_count: int = 0
    tool_call_count: int = 0
    done: bool = False
    failed: bool = False
    cancelled: bool = False
    status: str = "new"
    failure_reason: str | None = None
    cancel_reason: str | None = None
    cancel_requested_at: datetime | None = None
    cancel_signal_count: int = 0
    cancel_escalated: bool = False
    current_turn_id: str | None = None
    current_step_kind: StepKind | None = None
    current_step_id: str | None = None
    current_model_call_id: str | None = None
    terminal_status: TerminalStatus | None = None
    final_output: str = ""
    final_diff: str = ""
    workspace_envelope: WorkspaceEnvelope | None = None
    model_spec: dict[str, Any] = field(default_factory=dict)
    model_conversation_state: ModelConversationState | None = None
    approval_mode: ApprovalMode = "yolo"
    session_mode: SessionMode = "normal"
    pending_approvals: dict[str, ApprovalRequest] = field(default_factory=dict)
    approval_grants: dict[str, ApprovalGrant] = field(default_factory=dict)
    finalization_attempted: bool = False
    shell_preflight: dict[str, Any] = field(default_factory=dict)
    persist_events: bool = True
    stream_sink: EventSink | None = None
    cancel_token: CancelToken = field(default_factory=CancelToken, repr=False)
    context_state: ContextState = field(default_factory=_default_context_state)
    context_checkpoint: str = ""
    context_checkpoint_artifact: str = ""
    context_checkpoint_tool_step_count: int = 0
    context_token_estimate: int = 0
    compaction_count: int = 0
    skill_registry: Any | None = None
    context_registry: Any | None = None
    workspace_index: Any | None = None
    transcript: Transcript = field(default_factory=_default_transcript)
    observations: list[Observation] = field(default_factory=list)
    finish_gate_messages: list[str] = field(default_factory=list)
    prior_messages: tuple[Message, ...] = ()
    prior_context_artifact: str = ""
    parent_run_id: str | None = None
    parent_event_id: str | None = None
    branch_name: str | None = None
    _event_lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False, compare=False)

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
        parent_run_id: str | None = None,
        parent_event_id: str | None = None,
        branch_name: str | None = None,
        prior_messages: Sequence[Message] = (),
    ) -> RunState:
        resolved_workspace = Workspace(workspace.resolved_root())
        if not resolved_workspace.root.exists() or not resolved_workspace.root.is_dir():
            raise ValueError(f"Workspace does not exist or is not a directory: {resolved_workspace.root}")
        resolved_run_id = run_id or f"run_{uuid4().hex}"
        resolved_output_dir = (
            output_dir.expanduser().resolve() if output_dir else resolved_workspace.root / ".tinyagent" / "runs" / resolved_run_id
        )
        return cls(
            run_id=resolved_run_id,
            task=task,
            workspace=resolved_workspace,
            output_dir=resolved_output_dir,
            budgets=budgets or RunBudgets(),
            parent_run_id=parent_run_id,
            parent_event_id=parent_event_id,
            branch_name=branch_name,
            prior_messages=tuple(prior_messages),
        )

    def emit(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        visibility: EventVisibility = "debug",
        durability: EventDurability = "event_log",
        artifact_refs: list[str] | None = None,
        turn_id: str | None = None,
        item_id: str | None = None,
        parent_item_id: str | None = None,
    ) -> Event:
        # Single event boundary: durable events go to events.jsonl and sinks,
        # ephemeral events go to sinks only, and large payloads go to artifacts.
        with self._event_lock:
            event = Event(
                run_id=self.run_id,
                type=event_type,
                data=data or {},
                visibility=visibility,
                durability=durability,
                artifact_refs=artifact_refs or [],
                turn_id=turn_id if turn_id is not None else self.current_turn_id,
                item_id=item_id,
                parent_item_id=parent_item_id,
                seq=self.seq + 1,
            )
            self.seq = event.seq
            if event.durability == "event_log":
                self.events.append(event)
            if event.durability == "event_log" and self.persist_events:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                with (self.output_dir / "events.jsonl").open("a") as file:
                    file.write(json.dumps(event.to_json_dict(), sort_keys=True) + "\n")
            if self.stream_sink is not None:
                self.stream_sink.emit(event)
            return event

    def elapsed_seconds(self) -> float:
        return (utc_now() - self.started_at).total_seconds()

    def fail(self, reason: str) -> None:
        if self.done:
            return
        self.done = True
        self.failed = True
        self.status = "failed"
        self.terminal_status = "failed"
        self.failure_reason = reason

    def finish(self, final_output: str = "") -> None:
        if self.done:
            return
        self.done = True
        self.status = "completed"
        self.terminal_status = "completed"
        self.final_output = final_output or self.final_output

    def request_cancel(self, reason: str = "cancelled", *, source: str = "harness", escalate: bool = False) -> bool:
        already_cancelled = self.cancelled
        if source == "sigint":
            self.cancel_signal_count = max(self.cancel_signal_count, self.cancel_token.signal_count or self.cancel_signal_count + 1)
        self.cancel_token.cancel(reason, escalate=escalate)
        self.cancel_escalated = self.cancel_escalated or escalate or self.cancel_token.escalated
        if already_cancelled:
            return False
        self.done = True
        self.cancelled = True
        self.status = "cancelling"
        self.terminal_status = "cancelled"
        self.cancel_reason = reason
        self.cancel_requested_at = utc_now()
        if self.current_step_id:
            self.emit(
                "step.cancel.requested",
                {
                    "reason": reason,
                    "source": source,
                    "step_kind": self.current_step_kind,
                    "step_id": self.current_step_id,
                    "escalated": self.cancel_escalated,
                },
                visibility="user",
            )
        self.emit(
            "run.cancel.requested",
            {
                "reason": reason,
                "source": source,
                "current_step_kind": self.current_step_kind,
                "current_step_id": self.current_step_id,
                "escalated": self.cancel_escalated,
            },
            visibility="user",
        )
        return True

    def raise_if_cancelled(self) -> None:
        if self.cancel_token.cancelled:
            self.request_cancel(
                self.cancel_token.reason or "cancelled",
                source="sigint" if self.cancel_token.reason == "sigint" else "harness",
                escalate=self.cancel_token.escalated,
            )
        if self.cancelled:
            raise RunCancelled(self.cancel_reason or "cancelled")

    def start_turn(self, turn_id: str) -> None:
        self.current_turn_id = turn_id
        self.turn_count += 1
        self.emit("turn.started", {"turn_id": turn_id}, visibility="user", turn_id=turn_id)

    def finish_turn(self) -> None:
        if not self.current_turn_id:
            return
        event_type = "turn.interrupted" if self.cancelled else "turn.failed" if self.failed else "turn.completed"
        if not any(event.type == event_type and event.turn_id == self.current_turn_id for event in self.events):
            self.emit(
                event_type,
                {
                    "turn_id": self.current_turn_id,
                    "status": self.terminal_status or self.status,
                    "model_call_count": self.model_call_count,
                    "tool_call_count": self.tool_call_count,
                },
                visibility="user",
                turn_id=self.current_turn_id,
            )
        self.current_turn_id = None

    def start_step(
        self,
        kind: StepKind,
        step_id: str,
        *,
        data: dict[str, Any] | None = None,
        model_call_id: str | None = None,
    ) -> None:
        self.current_step_kind = kind
        self.current_step_id = step_id
        if model_call_id is not None:
            self.current_model_call_id = model_call_id
        payload = {"step_kind": kind, "step_id": step_id, **(data or {})}
        if self.current_model_call_id:
            payload.setdefault("model_call_id", self.current_model_call_id)
        self.emit("step.started", payload)

    def finish_step(
        self,
        status: Literal["completed", "failed", "cancelled", "timeout", "idle_timeout"],
        *,
        data: dict[str, Any] | None = None,
    ) -> None:
        if not self.current_step_id or not self.current_step_kind:
            return
        event_type = {
            "completed": "step.completed",
            "failed": "step.failed",
            "cancelled": "step.cancelled",
            "timeout": "step.timeout",
            "idle_timeout": "step.idle_timeout",
        }[status]
        payload = {"step_kind": self.current_step_kind, "step_id": self.current_step_id, **(data or {})}
        if self.current_model_call_id:
            payload.setdefault("model_call_id", self.current_model_call_id)
        self.emit(event_type, payload, visibility="user" if status != "completed" else "debug")
        self.set_current_step(None, None)

    def set_current_step(self, kind: StepKind | None, step_id: str | None) -> None:
        self.current_step_kind = kind
        self.current_step_id = step_id
        if kind != "model_call":
            self.current_model_call_id = None
