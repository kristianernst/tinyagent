"""Workspace index protocols."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from tinyagent.core.context_sources.types import ContextChunk

IndexMode = Literal["auto", "exact", "semantic", "hybrid", "fast"]
SyncMode = Literal["fast", "full", "overlay-fast", "embed"]


@dataclass(frozen=True)
class IndexStatus:
    backend: str
    ready: bool
    lexical_ready: bool
    semantic_ready: bool
    rerank_ready: bool
    stale_file_count: int
    indexed_file_count: int
    last_sync_at: str | None
    error: str = ""


@dataclass(frozen=True)
class SyncResult:
    backend: str
    mode: SyncMode
    synced_file_count: int = 0
    stale_file_count: int = 0
    duration_ms: int = 0
    error: str = ""


@dataclass(frozen=True)
class IndexHit:
    ref: str
    path: str
    kind: str
    title: str
    summary: str
    score: float | None
    line_start: int | None
    line_end: int | None
    backend: str
    freshness: str
    snippet: str = ""
    explanation: str = ""


class WorkspaceIndex(Protocol):
    name: str

    def status(self) -> IndexStatus: ...

    def sync(
        self,
        *,
        root: Path,
        paths: Sequence[str] | None = None,
        mode: SyncMode = "fast",
    ) -> SyncResult: ...

    def search(
        self,
        query: str,
        *,
        root: Path,
        path: str | None = None,
        kind: str | None = None,
        mode: IndexMode = "auto",
        limit: int = 10,
        explain: bool = False,
    ) -> Sequence[IndexHit]: ...

    def read(self, ref: str, *, root: Path, start_line: int | None = None, max_lines: int | None = None) -> ContextChunk: ...
