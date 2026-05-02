"""Event records and live sinks emitted by the tinyagent runtime."""

from __future__ import annotations

import json
import os
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
        "context.built",
        "compaction.started",
        "checkpoint.completed",
        "model.request.started",
        "model.stream.started",
        "model.completed",
        "model.failed",
        "model.cancelled",
        "model.usage",
        "message.completed",
        "tool.call.started",
        "tool.args.completed",
        "tool.policy.evaluated",
        "tool.execution.started",
        "tool.execution.completed",
        "tool.execution.failed",
        "tool.execution.cancelled",
        "shell.preflight.completed",
        "files.listed",
        "file.read",
        "search.completed",
        "command.started",
        "command.completed",
        "command.cancelled",
        "patch.applied",
        "diff.finalized",
        "artifact.created",
    }
)

LIVE_ONLY_EVENT_TYPES = frozenset(
    {
        "model.text.delta",
        "reasoning.summary.delta",
        "reasoning.visible.delta",
        "reasoning.encrypted",
        "tool.args.delta",
    }
)

EVENT_TYPES = DURABLE_EVENT_TYPES | LIVE_ONLY_EVENT_TYPES

EVENT_DEBUG_LEVELS = {
    "run.started": 0,
    "run.completed": 0,
    "run.failed": 0,
    "run.cancel.requested": 0,
    "run.cancelled": 0,
    "message.completed": 0,
    "model.text.delta": 0,
    "model.failed": 0,
    "model.request.started": 1,
    "model.stream.started": 1,
    "model.completed": 1,
    "model.cancelled": 1,
    "model.usage": 1,
    "diff.finalized": 1,
    "context.built": 2,
    "compaction.started": 2,
    "checkpoint.completed": 2,
    "tool.call.started": 2,
    "tool.args.completed": 2,
    "tool.policy.evaluated": 2,
    "tool.execution.started": 2,
    "tool.execution.completed": 2,
    "tool.execution.failed": 2,
    "tool.execution.cancelled": 2,
    "shell.preflight.completed": 2,
    "files.listed": 2,
    "file.read": 2,
    "search.completed": 2,
    "command.started": 2,
    "command.completed": 2,
    "command.cancelled": 2,
    "patch.applied": 2,
    "artifact.created": 2,
    "tool.args.delta": 2,
    "reasoning.summary.delta": 1,
    "reasoning.visible.delta": 4,
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
    return EVENT_DEBUG_LEVELS.get(event.type, VISIBILITY_DEBUG_LEVELS.get(event.visibility, 1))


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

    def emit(self, event: Event) -> None:
        if event.type != "model.text.delta":
            return
        delta = event.data.get("delta")
        if not isinstance(delta, str) or not delta:
            return
        self.file.write(delta)
        self.file.flush()


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
