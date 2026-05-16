"""Shared models for FlowForge."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkItem:
    key: str
    title: str
    owner: str = "unassigned"
    status: str = "todo"
    points: int = 1
    priority: int = 5
