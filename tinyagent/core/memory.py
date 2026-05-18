"""Explicit file-backed persistent memory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tinyagent.core.context_sources.builtin import _read_text_chunk
from tinyagent.core.context_sources.types import ContextChunk, ContextRef
from tinyagent.core.state import RunState

MEMORY_DIR = Path(".tinyagent") / "memory"
USER_MEMORY_DIR = Path.home() / ".tinyagent" / "memory"
MEMORY_FILES = {
    "project": MEMORY_DIR / "project.md",
    "decisions": MEMORY_DIR / "decisions.md",
    "skills-index": MEMORY_DIR / "skills-index.md",
    "user": USER_MEMORY_DIR / "user.md",
    "user-notes": USER_MEMORY_DIR / "user.md",
}


@dataclass(frozen=True)
class MemoryFile:
    name: str
    path: Path
    content: str


class MemoryStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.expanduser().resolve()

    def path_for(self, name: str) -> Path:
        key = _normalize_name(name)
        rel = MEMORY_FILES[key]
        if rel.is_absolute():
            path = rel.expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            return path.resolve()
        path = (self.workspace / rel).resolve()
        root = (self.workspace / MEMORY_DIR).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Unsafe memory path: {name}") from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def read(self, name: str) -> MemoryFile:
        key = _normalize_name(name)
        path = self.path_for(key)
        if not path.exists():
            return MemoryFile(name=key, path=path, content="")
        return MemoryFile(name=key, path=path, content=path.read_text(errors="replace"))

    def append(self, name: str, text: str) -> MemoryFile:
        key = _normalize_name(name)
        path = self.path_for(key)
        prefix = "" if not path.exists() or not path.read_text(errors="replace").strip() else "\n"
        path.write_text((path.read_text(errors="replace") if path.exists() else "") + prefix + text.rstrip() + "\n")
        return self.read(key)

    def ensure(self, name: str) -> MemoryFile:
        key = _normalize_name(name)
        path = self.path_for(key)
        if not path.exists():
            path.write_text("")
        return self.read(key)


class PersistentMemorySource:
    name = "memory"
    description = "Explicit project memory files in .tinyagent/memory."
    priority = 60

    def search(self, query: str, *, workspace: Path, state: RunState, limit: int = 10, kind: str | None = None) -> list[ContextRef]:
        del state
        if kind and kind != "memory":
            return []
        refs: list[ContextRef] = []
        terms = [term for term in query.lower().split() if term]
        for item in _project_memory_files(workspace):
            text = item.content
            haystack = f"{item.name} {text}".lower()
            if terms and not all(term in haystack for term in terms):
                continue
            score = 1.0 if not terms else sum(haystack.count(term) for term in terms)
            refs.append(
                ContextRef(
                    ref=f"{self.name}:{item.name}",
                    source=self.name,
                    title=f"Memory: {item.name}",
                    kind="memory",
                    summary=_summary(text) or "Empty memory file.",
                    score=float(score),
                    path=item.path.relative_to(workspace).as_posix(),
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
        item = MemoryStore(workspace).read(ref)
        try:
            rel_path = item.path.relative_to(workspace).as_posix()
        except ValueError:
            rel_path = str(item.path)
        return _read_text_chunk(
            full_ref=f"{self.name}:{item.name}",
            source=self.name,
            title=f"Memory: {item.name}",
            text=item.content,
            start_line=start_line,
            max_lines=max_lines,
            metadata={"path": rel_path},
        )


def _project_memory_files(workspace: Path) -> list[MemoryFile]:
    store = MemoryStore(workspace)
    return [store.read(name) for name in ("project", "decisions", "skills-index") if store.path_for(name).exists()]


def _normalize_name(name: str) -> str:
    key = name.strip().lower().replace("_", "-")
    if key not in MEMORY_FILES:
        raise ValueError(f"Unknown memory file: {name}")
    return key


def _summary(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:180]
    return ""
