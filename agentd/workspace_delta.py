"""Workspace mutation detection around tool calls."""

from __future__ import annotations

import difflib
import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from agentd.output import write_text_artifact
from agentd.state import RunState, ToolCall

MAX_UNTRACKED_DIFF_BYTES = 1_000_000
IGNORED_NAMES = frozenset(
    {
        ".git",
        ".tinyagent",
        ".coverage",
        ".hypothesis",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage.xml",
        "dist",
        "htmlcov",
        "node_modules",
        "venv",
    }
)


@dataclass(frozen=True)
class FileStat:
    size: int
    mtime_ns: int
    mode: int
    digest: str = ""


@dataclass(frozen=True)
class WorkspaceSnapshot:
    is_git: bool
    paths: frozenset[str] = frozenset()
    path_fingerprints: dict[str, str] = field(default_factory=dict)
    dirty_paths: frozenset[str] = frozenset()
    manifest: dict[str, FileStat] = field(default_factory=dict)
    diff_stat: str = ""
    fingerprint: str = ""


@dataclass(frozen=True)
class WorkspaceDelta:
    mutated: bool
    paths: tuple[str, ...] = ()
    diff_stat: str = ""
    diff_artifact: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "mutated": self.mutated,
            "paths": list(self.paths),
            "diff_stat": self.diff_stat,
            "diff_artifact": self.diff_artifact,
        }


class WorkspaceDeltaObserver:
    def snapshot(self, state: RunState) -> WorkspaceSnapshot:
        manifest = _manifest(state)
        if _is_git_workspace(state.workspace.root):
            path_fingerprints = _git_path_fingerprints(state)
            return WorkspaceSnapshot(
                is_git=True,
                paths=frozenset(path_fingerprints),
                path_fingerprints=path_fingerprints,
                dirty_paths=frozenset(_dirty_git_paths(state)),
                manifest=manifest,
                diff_stat=_git_diff_stat(state),
                fingerprint=_fingerprint_map(path_fingerprints),
            )
        return WorkspaceSnapshot(is_git=False, manifest=manifest)

    def diff(self, state: RunState, before: WorkspaceSnapshot, after: WorkspaceSnapshot, call: ToolCall) -> WorkspaceDelta:
        del call
        if before.is_git and after.is_git:
            if before.fingerprint == after.fingerprint:
                return WorkspaceDelta(mutated=False)
            paths = tuple(sorted(_changed_git_paths(before.path_fingerprints, after.path_fingerprints)))
            if not paths:
                return WorkspaceDelta(mutated=False)
            artifact = _write_git_diff_artifact(state, paths, before.path_fingerprints, before.dirty_paths)
            return WorkspaceDelta(mutated=True, paths=paths, diff_stat=after.diff_stat, diff_artifact=artifact)
        if before.is_git != after.is_git:
            paths = tuple(sorted(_manifest_delta_paths(before.manifest, after.manifest)))
            artifact = _write_git_transition_artifact(state, before, after, paths)
            return WorkspaceDelta(mutated=True, paths=paths, diff_artifact=artifact)
        paths = tuple(sorted(_manifest_delta_paths(before.manifest, after.manifest)))
        if not paths:
            return WorkspaceDelta(mutated=False)
        artifact = _write_manifest_diff_artifact(state, before.manifest, after.manifest, paths)
        return WorkspaceDelta(mutated=True, paths=paths, diff_artifact=artifact)


def _is_git_workspace(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_status_paths(state: RunState) -> list[str]:
    return list(_git_status_entries(state))


def _git_status_entries(state: RunState) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(state.workspace.root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    entries: dict[str, str] = {}
    records = [record for record in result.stdout.split(b"\0") if record]
    index = 0
    while index < len(records):
        record = records[index].decode(errors="replace")
        status = record[:2] if len(record) >= 2 else "??"
        path = record[3:] if len(record) > 3 else ""
        for status_path in _expand_status_path(state, path):
            entries[status_path] = status
        if record.startswith(("R", "C")) and index + 1 < len(records):
            index += 1
            extra = records[index].decode(errors="replace")
            for status_path in _expand_status_path(state, extra):
                entries[status_path] = status
        index += 1
    return entries


def _expand_status_path(state: RunState, path: str) -> list[str]:
    if not path or _excluded_relative(state, path):
        return []
    candidate = state.workspace.root / path
    if candidate.is_dir():
        expanded: list[str] = []
        for child in sorted(candidate.rglob("*")):
            if child.is_file() and not _excluded_path(state, child):
                expanded.append(child.relative_to(state.workspace.root).as_posix())
        return expanded
    return [path]


def _git_diff_stat(state: RunState) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(state.workspace.root), "diff", "--stat", "HEAD", "--"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _dirty_git_paths(state: RunState) -> set[str]:
    return set(_git_status_entries(state)) | set(_git_index_entries(state))


def _git_path_fingerprints(state: RunState) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    status_entries = _git_status_entries(state)
    index_entries = _git_index_entries(state)
    for path in sorted(set(_git_tracked_paths(state)) | set(status_entries) | set(index_entries)):
        digest = hashlib.sha256()
        digest.update(path.encode())
        digest.update((status_entries.get(path) or "").encode())
        digest.update((index_entries.get(path) or "").encode())
        candidate = state.workspace.root / path
        if candidate.is_symlink():
            try:
                digest.update(f"symlink:{candidate.readlink()}".encode())
            except OSError:
                digest.update(b"<symlink-unavailable>")
        elif candidate.is_file():
            try:
                digest.update(str(candidate.stat().st_mode).encode())
            except OSError:
                digest.update(b"<stat-unavailable>")
            digest.update(_file_digest(candidate).encode())
        else:
            digest.update(b"<missing>")
        fingerprints[path] = digest.hexdigest()
    return fingerprints


def _git_tracked_paths(state: RunState) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(state.workspace.root), "ls-files", "-z"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [
        path.decode(errors="replace")
        for path in result.stdout.split(b"\0")
        if path and not _excluded_relative(state, path.decode(errors="replace"))
    ]


def _git_index_entries(state: RunState) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(state.workspace.root), "ls-files", "-s", "-z"],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}
    entries: dict[str, str] = {}
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        record = raw.decode(errors="replace")
        _, _, path = record.partition("\t")
        if path and not _excluded_relative(state, path):
            entries[path] = record
    return entries


def _fingerprint_map(fingerprints: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path, value in sorted(fingerprints.items()):
        digest.update(path.encode())
        digest.update(value.encode())
    return digest.hexdigest()


def _changed_git_paths(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}


def _write_git_diff_artifact(
    state: RunState,
    paths: tuple[str, ...],
    before_fingerprints: dict[str, str] | None = None,
    before_dirty_paths: frozenset[str] = frozenset(),
) -> str | None:
    safe_tracked_paths = tuple(path for path in paths if _git_path_tracked(state, path) and path not in before_dirty_paths)
    redacted_dirty_paths = tuple(path for path in paths if _git_path_tracked(state, path) and path in before_dirty_paths)
    try:
        if not safe_tracked_paths:
            content = ""
        elif _git_has_head(state):
            result = subprocess.run(
                ["git", "-C", str(state.workspace.root), "diff", "--no-ext-diff", "HEAD", "--", *safe_tracked_paths],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            content = result.stdout if result.returncode == 0 else result.stderr
        else:
            content = _join_parts(_git_diff_cached(state, safe_tracked_paths), _git_diff_worktree(state, safe_tracked_paths))
    except (OSError, subprocess.TimeoutExpired) as exc:
        content = f"git diff unavailable: {exc}\n"
    dirty_summary = ""
    if redacted_dirty_paths:
        dirty_summary = "Tracked paths already dirty before this tool call; full diff redacted:\n" + "\n".join(redacted_dirty_paths) + "\n"
    before_fingerprints = before_fingerprints or {}
    untracked_diff = "".join(
        _git_untracked_diff(state, path, existed_before=path in before_fingerprints)
        for path in paths
        if not _git_path_tracked(state, path)
    )
    content = _join_parts(content, dirty_summary, untracked_diff)
    if not content.strip():
        content = "Workspace mutation detected, but no tracked diff was available.\nChanged paths:\n" + "\n".join(paths) + "\n"
    return write_text_artifact(state, f"workspace-delta-{state.tool_call_count:04d}.patch", content, kind="workspace_delta")


def _git_has_head(state: RunState) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(state.workspace.root), "rev-parse", "--verify", "HEAD"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _git_diff_cached(state: RunState, paths: tuple[str, ...]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(state.workspace.root), "diff", "--no-ext-diff", "--cached", "--", *paths],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git cached diff unavailable: {exc}\n"
    return result.stdout if result.returncode == 0 else result.stderr


def _git_diff_worktree(state: RunState, paths: tuple[str, ...]) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(state.workspace.root), "diff", "--no-ext-diff", "--", *paths],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"git worktree diff unavailable: {exc}\n"
    return result.stdout if result.returncode == 0 else result.stderr


def _git_path_tracked(state: RunState, path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(state.workspace.root), "ls-files", "--error-unmatch", "--", path],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _git_untracked_diff(state: RunState, path: str, *, existed_before: bool) -> str:
    candidate = state.workspace.root / path
    if _excluded_relative(state, path) or candidate.is_symlink() or not candidate.is_file():
        return ""
    if existed_before:
        return f"diff --git a/{path} b/{path}\n# Modified pre-existing untracked file; previous content was not retained.\n"
    body = "\n".join(_new_file_diff_lines(candidate))
    if not body:
        return ""
    return f"diff --git a/{path} b/{path}\nnew file mode 100644\nindex 0000000..0000000\n{body}\n"


def _join_parts(*parts: str) -> str:
    output = ""
    for part in parts:
        if not part:
            continue
        if output and not output.endswith("\n"):
            output += "\n"
        output += part
    return output


def _manifest(state: RunState) -> dict[str, FileStat]:
    root = state.workspace.root.resolve()
    manifest: dict[str, FileStat] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _excluded_path(state, path):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        manifest[rel] = FileStat(size=stat.st_size, mtime_ns=stat.st_mtime_ns, mode=stat.st_mode, digest=_file_digest(path))
    return manifest


def _manifest_delta_paths(before: dict[str, FileStat], after: dict[str, FileStat]) -> set[str]:
    changed: set[str] = set()
    for path in before.keys() | after.keys():
        old = before.get(path)
        new = after.get(path)
        if old is None or new is None:
            changed.add(path)
        elif old != new:
            changed.add(path)
    return changed


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def _write_manifest_diff_artifact(
    state: RunState,
    before: dict[str, FileStat],
    after: dict[str, FileStat],
    paths: tuple[str, ...],
) -> str:
    lines = ["# Workspace Delta", ""]
    for path in paths:
        old = before.get(path)
        new = after.get(path)
        if old is None:
            lines.append(f"A {path}")
            lines.extend(_new_file_diff_lines(state.workspace.root / path))
        elif new is None:
            lines.append(f"D {path}")
        else:
            lines.append(f"M {path}")
            lines.append("metadata changed; previous content was not retained for non-git diffing")
    return write_text_artifact(state, f"workspace-delta-{state.tool_call_count:04d}.patch", "\n".join(lines) + "\n", kind="workspace_delta")


def _write_git_transition_artifact(state: RunState, before: WorkspaceSnapshot, after: WorkspaceSnapshot, paths: tuple[str, ...]) -> str:
    lines = [
        "# Workspace Delta",
        "",
        f"Git workspace state changed: {'git' if before.is_git else 'non-git'} -> {'git' if after.is_git else 'non-git'}",
    ]
    if not paths:
        lines.append("No filtered workspace files changed; only git metadata changed.")
    else:
        lines.extend(("", "Changed files:"))
        for path in paths:
            lines.append(f"- {path}")
    return write_text_artifact(state, f"workspace-delta-{state.tool_call_count:04d}.patch", "\n".join(lines) + "\n", kind="workspace_delta")


def _new_file_diff_lines(path: Path) -> list[str]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if path.is_symlink():
        return []
    if size > MAX_UNTRACKED_DIFF_BYTES:
        return [f"Binary files /dev/null and {path.as_posix()} differ"]
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    if b"\0" in raw:
        return [f"Binary files /dev/null and {path.as_posix()} differ"]
    new_text = raw.decode(errors="replace").splitlines()
    return list(difflib.unified_diff([], new_text, fromfile="/dev/null", tofile=path.as_posix(), lineterm=""))


def _excluded_path(state: RunState, path: Path) -> bool:
    root = state.workspace.root.resolve()
    try:
        relative = path.resolve().relative_to(root)
    except ValueError:
        return True
    if any(part in IGNORED_NAMES for part in relative.parts):
        return True
    try:
        path.resolve().relative_to(state.output_dir.resolve())
        return True
    except ValueError:
        return False


def _excluded_relative(state: RunState, path: str) -> bool:
    parts = Path(path).parts
    if any(part in IGNORED_NAMES for part in parts):
        return True
    if _looks_like_secret_path(parts):
        return True
    try:
        output_relative = state.output_dir.resolve().relative_to(state.workspace.root.resolve()).as_posix()
    except ValueError:
        return False
    return path == output_relative or path.startswith(f"{output_relative}/")


def _looks_like_secret_path(parts: tuple[str, ...]) -> bool:
    for part in parts:
        if part == ".ssh":
            return True
        if part in {".env", ".npmrc", ".pypirc", ".netrc"} or part.startswith(".env."):
            return True
    return False
