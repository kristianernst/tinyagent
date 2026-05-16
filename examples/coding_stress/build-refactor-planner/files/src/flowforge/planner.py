"""Milestone planner."""

from __future__ import annotations

from flowforge.models import WorkItem


def next_items(items: list[WorkItem], limit: int = 5) -> list[WorkItem]:
    open_items = [item for item in items if item.status != "done"]
    return sorted(open_items, key=lambda item: (item.priority, item.key))[:limit]
