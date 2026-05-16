"""Backlog parser."""

from __future__ import annotations

from flowforge.models import WorkItem


def parse_backlog(text: str) -> list[WorkItem]:
    items: list[WorkItem] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        key, title, *fields = parts
        values = dict(_field_value(field) for field in fields if "=" in field)
        items.append(
            WorkItem(
                key=key,
                title=title,
                owner=values.get("owner", "unassigned"),
                status=values.get("status", "todo"),
                points=int(values.get("points", "1")),
                priority=int(values.get("priority", "5")),
            )
        )
    return items


def _field_value(field: str) -> tuple[str, str]:
    key, value = field.split("=", 1)
    return key.strip(), value.strip()
