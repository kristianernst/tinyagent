"""Event records emitted by the tinyagent runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

EVENT_TYPES = frozenset(
    {
        "RunStarted",
        "RunFinished",
        "RunFailed",
        "ContextBuilt",
        "ModelRequest",
        "ModelResponse",
        "ToolCallRequested",
        "PolicyDecision",
        "ToolCallStarted",
        "ToolCallFinished",
        "CommandStarted",
        "CommandFinished",
        "PatchApplied",
        "FileRead",
        "SearchCompleted",
        "DiffSnapshot",
        "ArtifactWritten",
    }
)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Event:
    """Single append-only runtime event."""

    run_id: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    parent_event_id: str | None = None
    id: str = field(default_factory=lambda: f"evt_{uuid4().hex}")
    time: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"Unknown event type: {self.type}")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "type": self.type,
            "time": self.time.isoformat().replace("+00:00", "Z"),
            "parent_event_id": self.parent_event_id,
            "data": json_safe(self.data),
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> Event:
        timestamp = data["time"].replace("Z", "+00:00")
        return cls(
            id=data["id"],
            run_id=data["run_id"],
            type=data["type"],
            time=datetime.fromisoformat(timestamp),
            parent_event_id=data.get("parent_event_id"),
            data=data.get("data", {}),
        )


def load_events_jsonl(path: Path) -> list[Event]:
    return [Event.from_json_dict(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


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
