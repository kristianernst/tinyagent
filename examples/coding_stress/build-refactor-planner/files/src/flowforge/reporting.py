"""Report rendering."""

from __future__ import annotations

from collections import Counter

from flowforge.models import WorkItem


def render_summary(items: list[WorkItem]) -> str:
    counts = Counter(item.status for item in items)
    total_points = sum(item.points for item in items)
    lines = ["FlowForge summary", f"total_items: {len(items)}", f"total_points: {total_points}"]
    for status, count in sorted(counts.items()):
        lines.append(f"{status}: {count}")
    return "\n".join(lines) + "\n"
