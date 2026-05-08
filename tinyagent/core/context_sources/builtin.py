"""Built-in dynamic context sources."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tinyagent.core.context_sources.types import ContextChunk, ContextRef, ContextSource
from tinyagent.core.contextfs import allowed_context_read_paths, relative_output_path, resolve_context_path
from tinyagent.core.skills import SkillRegistry
from tinyagent.core.state import RunState

MAX_CONTEXT_SOURCE_READ_BYTES = 1_000_000
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class ContextFsSource:
    name = "contextfs"
    description = "Current run ContextFS files, observations, transcript, failures, and safe tool output artifacts."
    priority = 100

    def search(self, query: str, *, workspace: Path, state: RunState, limit: int = 10, kind: str | None = None) -> list[ContextRef]:
        del workspace
        refs: list[ContextRef] = []
        for rel in sorted(allowed_context_read_paths(state)):
            path = state.output_dir / rel
            if path.is_file():
                ref = _file_match_ref(query, source=self.name, rel=rel, path=path, default_kind=_kind_for_contextfs_path(rel))
                if ref is not None and _kind_matches(ref, kind):
                    refs.append(ref)
        return sorted(refs, key=lambda ref: ref.score or 0, reverse=True)[:limit]

    def read(
        self,
        ref: str,
        *,
        workspace: Path,
        state: RunState,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> ContextChunk:
        del workspace
        path = resolve_context_path(state, ref)
        text = _read_bounded_text(path)
        return _read_text_chunk(
            full_ref=f"{self.name}:{relative_output_path(state, path)}",
            source=self.name,
            title=relative_output_path(state, path),
            text=text,
            start_line=start_line,
            max_lines=max_lines,
        )


class ConversationSource:
    name = "conversation"
    description = "Prior messages in the active conversation."
    priority = 90

    def search(self, query: str, *, workspace: Path, state: RunState, limit: int = 10, kind: str | None = None) -> list[ContextRef]:
        del workspace
        if kind and kind != "conversation_turn":
            return []
        refs: list[ContextRef] = []
        terms = _terms(query)
        for index, message in enumerate(state.prior_messages, start=1):
            text = str(message.content)
            score = _score(query, terms, f"{message.role} {text}")
            if score <= 0:
                continue
            refs.append(
                ContextRef(
                    ref=f"{self.name}:prior/{index}",
                    source=self.name,
                    title=f"Prior message {index} ({message.role})",
                    kind="conversation_turn",
                    summary=_summary(text),
                    score=score,
                    metadata={"role": message.role, "index": index},
                )
            )
        return sorted(refs, key=lambda ref: ref.score or 0, reverse=True)[:limit]

    def read(
        self,
        ref: str,
        *,
        workspace: Path,
        state: RunState,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> ContextChunk:
        del workspace
        prefix = "prior/"
        if not ref.startswith(prefix):
            raise KeyError(ref)
        index = int(ref[len(prefix) :])
        if index < 1 or index > len(state.prior_messages):
            raise KeyError(ref)
        message = state.prior_messages[index - 1]
        content = f"role: {message.role}\n\n{message.content}"
        return _read_text_chunk(
            full_ref=f"{self.name}:{ref}",
            source=self.name,
            title=f"Prior message {index} ({message.role})",
            text=content,
            start_line=start_line,
            max_lines=max_lines,
            metadata={"role": message.role, "index": index},
        )


class PastRunsSource:
    name = "past_runs"
    description = "Final outputs and summaries from previous runs in the current workspace."
    priority = 65

    def search(self, query: str, *, workspace: Path, state: RunState, limit: int = 10, kind: str | None = None) -> list[ContextRef]:
        del workspace
        if kind and kind != "run_final":
            return []
        refs: list[ContextRef] = []
        runs_root = state.output_dir.parent
        if not runs_root.exists():
            return []
        terms = _terms(query)
        for run_dir in sorted(runs_root.iterdir(), key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True):
            if run_dir.name == state.run_id or not run_dir.is_dir():
                continue
            final_path = run_dir / "final.md"
            metrics_path = run_dir / "metrics.json"
            haystack = final_path.read_text(errors="replace") if final_path.exists() else ""
            task = _metrics_task(metrics_path)
            score = _score(query, terms, f"{run_dir.name} {task} {haystack}")
            if score <= 0:
                continue
            refs.append(
                ContextRef(
                    ref=f"{self.name}:{run_dir.name}/final.md",
                    source=self.name,
                    title=f"Past run {run_dir.name}",
                    kind="run_final",
                    summary=_summary(task or haystack),
                    score=score,
                    path=f"{run_dir.name}/final.md",
                )
            )
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
        del workspace
        if "/" not in ref:
            raise KeyError(ref)
        run_id, rel = ref.split("/", 1)
        if not RUN_ID_PATTERN.fullmatch(run_id) or rel != "final.md":
            raise ValueError(f"Unsafe past-run ref: {ref}")
        path = (state.output_dir.parent / run_id / rel).resolve()
        runs_root = state.output_dir.parent.resolve()
        try:
            path.relative_to(runs_root)
        except ValueError as exc:
            raise ValueError(f"Unsafe past-run ref: {ref}") from exc
        if not path.is_file():
            raise KeyError(ref)
        return _read_text_chunk(
            full_ref=f"{self.name}:{ref}",
            source=self.name,
            title=f"Past run {run_id} final output",
            text=_read_bounded_text(path),
            start_line=start_line,
            max_lines=max_lines,
        )


class SkillContextSource:
    name = "skills"
    description = "Available skill names, descriptions, tags, and SKILL.md files."
    priority = 80

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or SkillRegistry()

    def search(self, query: str, *, workspace: Path, state: RunState, limit: int = 10, kind: str | None = None) -> list[ContextRef]:
        del state
        if kind and kind != "skill":
            return []
        terms = _terms(query)
        refs: list[ContextRef] = []
        for skill in self.registry.list(workspace):
            score = _score(query, terms, f"{skill.name} {skill.description} {' '.join(skill.tags)}")
            if score <= 0:
                continue
            refs.append(
                ContextRef(
                    ref=f"{self.name}:{skill.id}/SKILL.md",
                    source=self.name,
                    title=skill.name,
                    kind="skill",
                    summary=skill.description,
                    score=score,
                    path=skill.path,
                    metadata={"skill_id": skill.id, "tags": list(skill.tags), "source": skill.source},
                )
            )
        return sorted(refs, key=lambda ref: ref.score or 0, reverse=True)[:limit]

    def read(
        self,
        ref: str,
        *,
        workspace: Path,
        state: RunState,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> ContextChunk:
        del state
        skill_id = ref.removesuffix("/SKILL.md")
        loaded = self.registry.load(skill_id, workspace)
        return _read_text_chunk(
            full_ref=f"{self.name}:{skill_id}/SKILL.md",
            source=self.name,
            title=loaded.ref.name,
            text=loaded.markdown,
            start_line=start_line,
            max_lines=max_lines,
            metadata={
                "skill_id": loaded.ref.id,
                "source": loaded.ref.source,
                "path": loaded.ref.path,
                "files": list(loaded.files),
            },
        )


class WorkspaceIndexSource:
    name = "workspace_index"
    description = "Workspace code and docs search through the local index with rg fallback."
    priority = 85

    def search(self, query: str, *, workspace: Path, state: RunState, limit: int = 10, kind: str | None = None) -> list[ContextRef]:
        hits = _workspace_index(state, workspace).search(query, root=workspace, kind=kind, limit=limit)
        return [
            ContextRef(
                ref=f"{self.name}:{hit.ref}",
                source=self.name,
                title=hit.title,
                kind=hit.kind,
                summary=hit.summary,
                score=hit.score,
                path=hit.path,
                line_start=hit.line_start,
                line_end=hit.line_end,
                metadata={"backend": hit.backend, "freshness": hit.freshness},
            )
            for hit in hits
        ]

    def read(
        self,
        ref: str,
        *,
        workspace: Path,
        state: RunState,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> ContextChunk:
        return _workspace_index(state, workspace).index.read(ref, root=workspace, start_line=start_line, max_lines=max_lines)


def default_context_sources(skill_registry: SkillRegistry | None = None) -> tuple[ContextSource, ...]:
    return (
        ContextFsSource(),
        ConversationSource(),
        PastRunsSource(),
        SkillContextSource(skill_registry),
        WorkspaceIndexSource(),
    )


def _file_match_ref(query: str, *, source: str, rel: str, path: Path, default_kind: str) -> ContextRef | None:
    terms = _terms(query)
    try:
        text = _read_bounded_text(path)
    except ValueError:
        if _score(query, terms, rel) <= 0:
            return None
        return ContextRef(
            ref=f"{source}:{rel}",
            source=source,
            title=rel,
            kind=default_kind,
            summary="File is too large for context_search.",
            score=0.1,
            path=rel,
        )
    score = _score(query, terms, f"{rel}\n{text}")
    if score <= 0:
        return None
    return ContextRef(
        ref=f"{source}:{rel}",
        source=source,
        title=rel,
        kind=default_kind,
        summary=_summary(text),
        score=score,
        path=rel,
    )


def _workspace_index(state: RunState, workspace: Path):
    from tinyagent.core.index import WorkspaceIndexManager

    if isinstance(state.workspace_index, WorkspaceIndexManager):
        return state.workspace_index
    return WorkspaceIndexManager.for_workspace(workspace)


def _read_text_chunk(
    *,
    full_ref: str,
    source: str,
    title: str,
    text: str,
    start_line: int | None,
    max_lines: int | None,
    metadata: dict | None = None,
) -> ContextChunk:
    start = max(start_line or 1, 1)
    limit = max(max_lines or 400, 1)
    lines = text.splitlines()
    selected = lines[start - 1 : start - 1 + limit]
    end = start + len(selected) - 1 if selected else start - 1
    return ContextChunk(
        ref=full_ref,
        source=source,
        title=title,
        content="\n".join(selected),
        start_line=start,
        end_line=end,
        total_lines=len(lines),
        truncated=end < len(lines),
        metadata=metadata or {},
    )


def _terms(query: str) -> tuple[str, ...]:
    return tuple(term for term in query.lower().split() if term)


def _score(query: str, terms: tuple[str, ...], text: str) -> float:
    haystack = text.lower()
    if query.lower() in haystack:
        return 100.0 + len(query)
    hits = sum(1 for term in terms if term in haystack)
    return float(hits) if hits else 0.0


def _summary(text: str, *, limit: int = 180) -> str:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _kind_for_contextfs_path(path: str) -> str:
    if "failure" in path:
        return "failure"
    if "transcript" in path:
        return "transcript"
    if "observation" in path:
        return "observation"
    return "file"


def _kind_matches(ref: ContextRef, kind: str | None) -> bool:
    return kind is None or ref.kind == kind


def _metrics_task(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return ""
    return str(data.get("task") or "")


def _read_bounded_text(path: Path) -> str:
    if path.stat().st_size > MAX_CONTEXT_SOURCE_READ_BYTES:
        raise ValueError(f"context file is too large to read: {path.name} ({path.stat().st_size} bytes)")
    return path.read_text(errors="replace")
