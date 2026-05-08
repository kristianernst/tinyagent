"""Dynamic context source registry."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tinyagent.core.context_sources.types import ContextChunk, ContextRef, ContextSource, ContextSourceInfo
from tinyagent.core.state import RunState


class ContextRegistry:
    def __init__(self, sources: Sequence[ContextSource] = ()) -> None:
        self.sources: dict[str, list[ContextSource]] = {}
        for source in sources:
            self.register(source)

    def register(self, source: ContextSource) -> None:
        self.sources.setdefault(source.name, []).append(source)

    def list_sources(self) -> list[ContextSourceInfo]:
        infos: list[ContextSourceInfo] = []
        for name, sources in self.sources.items():
            priority = max(source.priority for source in sources)
            descriptions = tuple(dict.fromkeys(source.description for source in sources))
            infos.append(ContextSourceInfo(name=name, description=" / ".join(descriptions), priority=priority))
        return sorted(infos, key=lambda item: (-item.priority, item.name))

    def search(
        self,
        query: str,
        *,
        workspace: Path,
        state: RunState,
        source: str | None = None,
        kind: str | None = None,
        limit: int = 10,
    ) -> list[ContextRef]:
        selected = self._sources(source) if source else [item for group in self.sources.values() for item in group]
        refs: list[ContextRef] = []
        for item in selected:
            refs.extend(item.search(query, workspace=workspace, state=state, limit=limit, kind=kind))
        refs.sort(key=lambda ref: (ref.score if ref.score is not None else self._priority(ref.source), ref.source), reverse=True)
        return refs[:limit]

    def read(
        self,
        ref: str,
        *,
        workspace: Path,
        state: RunState,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> ContextChunk:
        source_name, local_ref = _split_ref(ref)
        last_error: Exception | None = None
        for source in self._sources(source_name):
            try:
                return source.read(local_ref, workspace=workspace, state=state, start_line=start_line, max_lines=max_lines)
            except (KeyError, ValueError, FileNotFoundError) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise KeyError(f"Unknown context source: {source_name}")

    def _sources(self, name: str | None) -> list[ContextSource]:
        if not name:
            raise KeyError("context source is required")
        if name not in self.sources:
            raise KeyError(f"Unknown context source: {name}")
        return self.sources[name]

    def _priority(self, name: str) -> int:
        sources = self.sources.get(name) or []
        return max((source.priority for source in sources), default=0)


def _split_ref(ref: str) -> tuple[str, str]:
    if ":" not in ref:
        raise ValueError(f"Context ref must include a source prefix: {ref}")
    source, local_ref = ref.split(":", 1)
    if not source or not local_ref:
        raise ValueError(f"Invalid context ref: {ref}")
    return source, local_ref


def context_registry_for_state(state: RunState) -> ContextRegistry:
    if isinstance(state.context_registry, ContextRegistry):
        return state.context_registry
    from tinyagent.core.context_sources.builtin import default_context_sources

    return ContextRegistry(default_context_sources(state.skill_registry))
