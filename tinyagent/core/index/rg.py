"""Fresh rg-backed workspace index fallback."""

from __future__ import annotations

import os
import selectors
import shutil
import subprocess
import time
from collections.abc import Sequence
from pathlib import Path

from tinyagent.core.context_sources.types import ContextChunk
from tinyagent.core.index.safety import (
    MAX_INDEX_FILE_BYTES,
    assert_index_file_readable,
    is_excluded_index_path,
    parse_code_ref,
    rg_exclude_globs,
)
from tinyagent.core.index.types import IndexHit, IndexMode, IndexStatus, SyncMode, SyncResult

MAX_RG_MATCHES = 50


class RgWorkspaceIndex:
    name = "rg"

    def __init__(self) -> None:
        self._last_sync_at: str | None = None
        self._error = ""
        self._env: dict[str, str] | None = None
        self._timeout_seconds = 10

    def configure_runtime(self, *, env: dict[str, str], timeout_seconds: int) -> None:
        self._env = dict(env)
        self._timeout_seconds = max(timeout_seconds, 1)

    def status(self) -> IndexStatus:
        ready = shutil.which("rg") is not None
        return IndexStatus(
            backend=self.name,
            ready=ready,
            lexical_ready=ready,
            semantic_ready=False,
            rerank_ready=False,
            stale_file_count=0,
            indexed_file_count=0,
            last_sync_at=self._last_sync_at,
            error=self._error,
        )

    def sync(self, *, root: Path, paths: Sequence[str] | None = None, mode: SyncMode = "fast") -> SyncResult:
        del root, paths
        started = time.monotonic()
        self._last_sync_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return SyncResult(backend=self.name, mode=mode, duration_ms=int((time.monotonic() - started) * 1000))

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
    ) -> Sequence[IndexHit]:
        if mode == "semantic":
            self._error = "semantic search unavailable for rg backend"
            return []
        if mode not in {"auto", "exact", "fast", "hybrid"}:
            self._error = f"unsupported search mode: {mode}"
            return []
        rg = shutil.which("rg")
        if rg is None:
            self._error = "rg unavailable"
            return _filter_kind(_python_search(root, query, path=path, limit=limit, explain=explain), kind)
        target = path or "."
        lines, _truncated, _timed_out = _run_rg(
            root,
            rg,
            query,
            target,
            max_matches=min(limit, MAX_RG_MATCHES),
            env=self._env or _safe_env(root),
            timeout_seconds=self._timeout_seconds,
        )
        return _filter_kind([_line_to_hit(line, explain=explain) for line in lines], kind)[:limit]

    def read(self, ref: str, *, root: Path, start_line: int | None = None, max_lines: int | None = None) -> ContextChunk:
        path_part, ref_line = parse_code_ref(ref)
        path = (root / path_part).resolve()
        assert_index_file_readable(root, path, ref=ref)
        text = path.read_text(errors="replace")
        start = max(start_line or ref_line or 1, 1)
        limit = max(max_lines or 400, 1)
        lines = text.splitlines()
        selected = lines[start - 1 : start - 1 + limit]
        return ContextChunk(
            ref=ref,
            source="workspace_index",
            title=path_part,
            content="\n".join(selected),
            start_line=start,
            end_line=start + len(selected) - 1 if selected else start - 1,
            total_lines=len(lines),
            truncated=start + len(selected) - 1 < len(lines),
        )


def _run_rg(
    root: Path,
    rg: str,
    query: str,
    target: str,
    *,
    max_matches: int,
    env: dict[str, str],
    timeout_seconds: int,
) -> tuple[list[str], bool, bool]:
    command = [
        rg,
        "--line-number",
        "--no-heading",
        "--color",
        "never",
        "--no-config",
        "--with-filename",
        "--max-filesize",
        f"{MAX_INDEX_FILE_BYTES}",
        "--max-columns",
        "240",
    ]
    command.extend(rg_exclude_globs())
    command.extend(["--", query, target])
    process = subprocess.Popen(command, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    assert process.stdout is not None
    lines: list[str] = []
    timed_out = False
    deadline = time.monotonic() + timeout_seconds
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                process.terminate()
                break
            for key, _mask in selector.select(timeout=0.05):
                chunk = key.fileobj.readline()
                if not chunk:
                    continue
                lines.append(chunk.decode(errors="replace").rstrip("\n"))
                if len(lines) >= max_matches + 1:
                    process.terminate()
                    break
        try:
            remainder, _stderr = process.communicate(timeout=0.5)
        except subprocess.TimeoutExpired:
            process.kill()
            remainder, _stderr = process.communicate()
        lines.extend(line for line in remainder.decode(errors="replace").splitlines() if line)
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
    return lines[: max_matches + 1], len(lines) > max_matches, timed_out


def _safe_env(root: Path) -> dict[str, str]:
    safe_keys = {"PATH", "USER", "USERNAME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "SHELL"}
    env = {key: value for key, value in os.environ.items() if key in safe_keys}
    env["HOME"] = str(root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _line_to_hit(line: str, *, explain: bool) -> IndexHit:
    path, line_number, snippet = _split_rg_line(line)
    path = path.removeprefix("./")
    line_int = int(line_number) if line_number.isdigit() else None
    return IndexHit(
        ref=f"code:{path}#L{line_int}" if line_int else f"code:{path}",
        path=path,
        kind=_kind_for_path(path),
        title=path,
        summary=snippet[:180],
        score=None,
        line_start=line_int,
        line_end=line_int,
        backend="rg",
        freshness="rg",
        snippet=snippet,
        explanation="fresh rg fallback result" if explain else "",
    )


def _split_rg_line(line: str) -> tuple[str, str, str]:
    parts = line.split(":", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return line, "", ""


def _python_search(root: Path, query: str, *, path: str | None, limit: int, explain: bool) -> Sequence[IndexHit]:
    base = (root / (path or ".")).resolve()
    try:
        base.relative_to(root.resolve())
    except ValueError:
        return []
    files = [base] if base.is_file() else [item for item in sorted(base.rglob("*")) if item.is_file()]
    hits: list[IndexHit] = []
    for file_path in files:
        if len(hits) >= limit:
            break
        if is_excluded_index_path(root, file_path):
            continue
        try:
            if file_path.stat().st_size > MAX_INDEX_FILE_BYTES:
                continue
            text = file_path.read_text(errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                rel = file_path.relative_to(root).as_posix()
                hits.append(
                    IndexHit(
                        ref=f"code:{rel}#L{line_number}",
                        path=rel,
                        kind=_kind_for_path(rel),
                        title=rel,
                        summary=line[:180],
                        score=None,
                        line_start=line_number,
                        line_end=line_number,
                        backend="python",
                        freshness="rg",
                        snippet=line,
                        explanation="python fallback result" if explain else "",
                    )
                )
                break
    return hits


def _kind_for_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".md", ".rst", ".txt"}:
        return "doc"
    if "/tests/" in path or Path(path).name.startswith("test_"):
        return "test"
    return "chunk"


def _filter_kind(hits: Sequence[IndexHit], kind: str | None) -> list[IndexHit]:
    if not kind:
        return list(hits)
    return [hit for hit in hits if hit.kind == kind]
