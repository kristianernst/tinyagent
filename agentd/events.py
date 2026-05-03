"""Event records and live sinks emitted by the tinyagent runtime."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO
from uuid import uuid4

EventVisibility = Literal["internal", "debug", "user", "public"]
EventDurability = Literal["ephemeral", "event_log", "artifact_only"]

DURABLE_EVENT_TYPES = frozenset(
    {
        "run.started",
        "run.completed",
        "run.failed",
        "run.cancel.requested",
        "run.cancelled",
        "run.forked",
        "run.timed_out",
        "turn.started",
        "turn.completed",
        "turn.interrupted",
        "turn.failed",
        "step.started",
        "step.completed",
        "step.failed",
        "step.cancel.requested",
        "step.cancelled",
        "step.timeout",
        "step.idle_timeout",
        "workspace.opened",
        "workspace.boundary",
        "workspace.dirty.detected",
        "workspace.mutation.planned",
        "workspace.mutation.started",
        "workspace.mutation.completed",
        "workspace.delta.started",
        "workspace.delta.completed",
        "workspace.mutation.detected",
        "file.changed",
        "diff.snapshot",
        "workspace.escape.detected",
        "worktree.created",
        "child_run.started",
        "child_run.completed",
        "child_run.failed",
        "context.built",
        "context.report.written",
        "contextfs.artifact.written",
        "contextfs.index.updated",
        "finish.blocked",
        "hook.started",
        "hook.completed",
        "hook.failed",
        "compaction.started",
        "checkpoint.completed",
        "model.call.started",
        "model.call.completed",
        "model.call.failed",
        "model.message.completed",
        "model.tool_call.assembly.started",
        "model.tool_call.assembly.completed",
        "model.tool_call.assembly.failed",
        "model.reasoning.completed",
        "model.timeout",
        "model.idle_timeout",
        "model.cancelled",
        "model.usage",
        "observation.recorded",
        "policy.evaluated",
        "approval.requested",
        "approval.resolved",
        "approval.expired",
        "tool.execution.started",
        "tool.execution.output.snapshot",
        "tool.execution.completed",
        "tool.execution.failed",
        "tool.execution.cancelled",
        "tool.execution.blocked",
        "shell.preflight.completed",
        "files.listed",
        "file.read",
        "search.completed",
        "command.started",
        "command.completed",
        "command.failed",
        "command.cancelled",
        "command.timeout",
        "patch.applied",
        "file.edited",
        "diff.finalized",
        "artifact.created",
        "artifact.finalization.started",
        "artifact.materialized",
        "artifact.finalization.completed",
        "artifact.finalization.failed",
    }
)

LIVE_ONLY_EVENT_TYPES = frozenset(
    {
        "model.text.delta",
        "model.reasoning.delta",
        "reasoning.encrypted",
        "model.tool_call.args.delta",
        "tool.execution.output.delta",
        "command.output.delta",
    }
)

EVENT_TYPES = DURABLE_EVENT_TYPES | LIVE_ONLY_EVENT_TYPES

EVENT_DEBUG_LEVELS = {
    "run.started": 0,
    "run.completed": 0,
    "run.failed": 0,
    "run.cancel.requested": 0,
    "run.cancelled": 0,
    "run.forked": 1,
    "run.timed_out": 0,
    "turn.started": 1,
    "turn.completed": 1,
    "turn.interrupted": 1,
    "turn.failed": 1,
    "step.started": 2,
    "step.completed": 2,
    "step.failed": 2,
    "step.cancel.requested": 1,
    "step.cancelled": 1,
    "step.timeout": 1,
    "step.idle_timeout": 1,
    "workspace.opened": 1,
    "workspace.boundary": 1,
    "workspace.dirty.detected": 1,
    "workspace.mutation.planned": 2,
    "workspace.mutation.started": 2,
    "workspace.mutation.completed": 2,
    "workspace.delta.started": 2,
    "workspace.delta.completed": 2,
    "workspace.mutation.detected": 1,
    "file.changed": 2,
    "diff.snapshot": 2,
    "workspace.escape.detected": 0,
    "worktree.created": 1,
    "child_run.started": 1,
    "child_run.completed": 1,
    "child_run.failed": 1,
    "model.message.completed": 0,
    "model.text.delta": 0,
    "model.call.failed": 0,
    "model.call.started": 1,
    "model.call.completed": 1,
    "model.cancelled": 1,
    "model.timeout": 1,
    "model.idle_timeout": 1,
    "model.usage": 1,
    "observation.recorded": 2,
    "model.tool_call.assembly.started": 2,
    "model.tool_call.assembly.completed": 2,
    "model.tool_call.assembly.failed": 1,
    "model.tool_call.args.delta": 2,
    "model.reasoning.delta": 1,
    "model.reasoning.completed": 1,
    "diff.finalized": 1,
    "context.built": 2,
    "context.report.written": 2,
    "contextfs.artifact.written": 2,
    "contextfs.index.updated": 2,
    "finish.blocked": 1,
    "hook.started": 2,
    "hook.completed": 2,
    "hook.failed": 1,
    "compaction.started": 2,
    "checkpoint.completed": 2,
    "policy.evaluated": 2,
    "approval.requested": 1,
    "approval.resolved": 1,
    "approval.expired": 1,
    "tool.execution.started": 2,
    "tool.execution.output.delta": 2,
    "tool.execution.output.snapshot": 2,
    "tool.execution.completed": 2,
    "tool.execution.failed": 2,
    "tool.execution.cancelled": 2,
    "tool.execution.blocked": 1,
    "shell.preflight.completed": 2,
    "files.listed": 2,
    "file.read": 2,
    "search.completed": 2,
    "command.started": 2,
    "command.output.delta": 3,
    "command.completed": 2,
    "command.failed": 2,
    "command.cancelled": 2,
    "command.timeout": 2,
    "patch.applied": 2,
    "file.edited": 2,
    "artifact.created": 2,
    "artifact.finalization.started": 2,
    "artifact.materialized": 2,
    "artifact.finalization.completed": 2,
    "artifact.finalization.failed": 1,
    "reasoning.encrypted": 4,
}

VISIBILITY_DEBUG_LEVELS = {
    "public": 0,
    "user": 0,
    "debug": 1,
    "internal": 4,
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def debug_level_from_env(env: dict[str, str] | None = None) -> int:
    values = os.environ if env is None else env
    raw = values.get("TINYAGENT_DEBUG", "0")
    try:
        level = int(raw)
    except ValueError as exc:
        raise ValueError("TINYAGENT_DEBUG must be an integer.") from exc
    if level < 0:
        raise ValueError("TINYAGENT_DEBUG must be non-negative.")
    return level


def event_debug_level(event: Event) -> int:
    level = EVENT_DEBUG_LEVELS.get(event.type, 1)
    if event.visibility == "internal":
        return max(level, VISIBILITY_DEBUG_LEVELS["internal"])
    return level


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return repr(value)


@dataclass(frozen=True)
class Event:
    """Single ordered runtime event.

    Durable and live-only stream events share this envelope. Durability decides
    whether an event is appended to the event log; visibility decides whether a
    sink should present it to users.
    """

    run_id: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    visibility: EventVisibility = "debug"
    durability: EventDurability = "event_log"
    artifact_refs: list[str] = field(default_factory=list)
    turn_id: str | None = None
    item_id: str | None = None
    parent_item_id: str | None = None
    source: str = "tinyagent"
    seq: int = 0
    id: str = field(default_factory=lambda: f"evt_{uuid4().hex}")
    time: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"Unknown event type: {self.type}")
        if self.type in LIVE_ONLY_EVENT_TYPES and self.durability != "ephemeral":
            raise ValueError(f"Live-only event cannot be durable: {self.type}")
        if self.durability == "event_log" and self.type not in DURABLE_EVENT_TYPES:
            raise ValueError(f"Event is not durable: {self.type}")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seq": self.seq,
            "type": self.type,
            "time": self.time.isoformat().replace("+00:00", "Z"),
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "item_id": self.item_id,
            "parent_item_id": self.parent_item_id,
            "source": self.source,
            "visibility": self.visibility,
            "durability": self.durability,
            "data": json_safe(self.data),
            "artifact_refs": json_safe(self.artifact_refs),
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> Event:
        timestamp = data["time"].replace("Z", "+00:00")
        return cls(
            id=data["id"],
            seq=int(data.get("seq", 0)),
            run_id=data["run_id"],
            type=data["type"],
            time=datetime.fromisoformat(timestamp),
            turn_id=data.get("turn_id"),
            item_id=data.get("item_id"),
            parent_item_id=data.get("parent_item_id"),
            source=data.get("source", "tinyagent"),
            visibility=data.get("visibility", "debug"),
            durability=data.get("durability", "event_log"),
            data=data.get("data", {}),
            artifact_refs=list(data.get("artifact_refs", [])),
        )


def load_events_jsonl(path: Path) -> list[Event]:
    return [Event.from_json_dict(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...


class NullSink:
    def emit(self, event: Event) -> None:
        del event


class ConsoleTextSink:
    def __init__(self, file: TextIO | None = None) -> None:
        self.file = file or sys.stdout
        self.at_line_start = True

    def emit(self, event: Event) -> None:
        if event.type == "model.text.delta":
            self._write_delta(event.data.get("delta"))
        elif event.type == "model.reasoning.delta" and event.visibility in {"public", "user"}:
            self._write_line(f"[reasoning] {_event_text(event)}")
        elif event.type == "model.tool_call.assembly.completed":
            tool = str(event.data.get("tool") or "tool")
            self._write_line(f"[tool] {tool}: {_tool_args_summary(event)}")
        elif event.type in {"tool.execution.completed", "tool.execution.failed", "tool.execution.cancelled", "tool.execution.blocked"}:
            self._write_line(_tool_status_summary(event))
        elif event.type in {"turn.completed", "turn.failed", "turn.interrupted", "run.completed", "run.failed", "run.cancelled"}:
            self._close_line()

    def _write_delta(self, value: Any) -> None:
        if not isinstance(value, str) or not value:
            return
        self.file.write(value)
        self.at_line_start = value.endswith("\n")
        self.file.flush()

    def _write_line(self, line: str) -> None:
        if not line:
            return
        self._close_line()
        self.file.write(line + "\n")
        self.at_line_start = True
        self.file.flush()

    def _close_line(self) -> None:
        if self.at_line_start:
            return
        self.file.write("\n")
        self.at_line_start = True
        self.file.flush()


def _event_text(event: Event) -> str:
    value = event.data.get("delta") or event.data.get("reason") or event.data.get("output") or ""
    return _clip_text(str(value).replace("\n", " "))


def _tool_args_summary(event: Event) -> str:
    args = event.data.get("args")
    if not isinstance(args, dict):
        return ""
    cmd = args.get("cmd")
    if isinstance(cmd, str) and cmd:
        return _clip_text(cmd)
    patch = args.get("patch")
    if isinstance(patch, str) and patch:
        paths = _patch_paths(patch)
        if paths:
            return ", ".join(paths)
        return "patch"
    return _clip_text(json.dumps(json_safe(args), sort_keys=True))


def _tool_status_summary(event: Event) -> str:
    tool = str(event.data.get("tool") or "tool")
    match event.type:
        case "tool.execution.completed":
            output_chars = event.data.get("output_chars")
            suffix = f", {output_chars} chars" if isinstance(output_chars, int) else ""
            return f"[ok] {tool} completed{suffix}"
        case "tool.execution.failed":
            return f"[fail] {tool}: {_event_text(event)}"
        case "tool.execution.cancelled":
            return f"[cancelled] {tool}: {_event_text(event)}"
        case "tool.execution.blocked":
            return f"[blocked] {tool}: {_event_text(event)}"
    return ""


def _patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        match = re.match(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", line)
        if match:
            paths.append(match.group(1))
            continue
        match = re.match(r"^\*\*\* Move to: (.+)$", line)
        if match:
            paths.append(match.group(1))
    return paths


def _clip_text(text: str, *, limit: int = 160) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


class JsonlStreamSink:
    def __init__(self, file: TextIO | None = None, *, debug_level: int = 0) -> None:
        self.file = file or sys.stdout
        self.debug_level = max(debug_level, 0)

    def emit(self, event: Event) -> None:
        if event_debug_level(event) > self.debug_level:
            return
        self.file.write(json.dumps(event.to_json_dict(), sort_keys=True) + "\n")
        self.file.flush()


class MemoryEventSink:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


class CompositeSink:
    def __init__(self, *sinks: EventSink) -> None:
        self.sinks = tuple(sinks)

    def emit(self, event: Event) -> None:
        for sink in self.sinks:
            sink.emit(event)
