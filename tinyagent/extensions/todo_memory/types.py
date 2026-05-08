"""Working todo state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

TodoStatus = Literal["open", "done"]


@dataclass(frozen=True)
class TodoItem:
    id: str
    text: str
    status: TodoStatus = "open"
    created_at: str = ""
    updated_at: str = ""
    source: str = "model"

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
        }


@dataclass(frozen=True)
class TodoState:
    version: int = 1
    items: tuple[TodoItem, ...] = ()
    notes: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {"version": self.version, "items": [item.to_json_dict() for item in self.items], "notes": self.notes}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodoState:
        return cls(
            version=int(data.get("version") or 1),
            items=tuple(_item_from_dict(item) for item in data.get("items") or [] if isinstance(item, dict)),
            notes=str(data.get("notes") or ""),
        )


def _item_from_dict(data: dict[str, Any]) -> TodoItem:
    status = str(data.get("status") or "open")
    return TodoItem(
        id=str(data.get("id") or ""),
        text=str(data.get("text") or ""),
        status="done" if status == "done" else "open",
        created_at=str(data.get("created_at") or ""),
        updated_at=str(data.get("updated_at") or ""),
        source=str(data.get("source") or "model"),
    )
