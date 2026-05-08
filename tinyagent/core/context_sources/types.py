"""Dynamic context source types."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from tinyagent.core.state import RunState


@dataclass(frozen=True)
class ContextRef:
    ref: str
    source: str
    title: str
    kind: str
    summary: str
    score: float | None = None
    path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextChunk:
    ref: str
    source: str
    title: str
    content: str
    start_line: int | None = None
    end_line: int | None = None
    total_lines: int | None = None
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextSourceInfo:
    name: str
    description: str
    priority: int = 0


class ContextSource(Protocol):
    name: str
    description: str
    priority: int

    def search(
        self,
        query: str,
        *,
        workspace: Path,
        state: RunState,
        limit: int = 10,
        kind: str | None = None,
    ) -> Sequence[ContextRef]: ...

    def read(
        self,
        ref: str,
        *,
        workspace: Path,
        state: RunState,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> ContextChunk: ...
