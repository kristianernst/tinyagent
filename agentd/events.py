"""Event records emitted by the tinyagent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


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

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "type": self.type,
            "time": self.time.isoformat().replace("+00:00", "Z"),
            "parent_event_id": self.parent_event_id,
            "data": self.data,
        }
