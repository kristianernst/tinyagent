"""Workspace surface helpers shared by HTTP runtimes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from tinyagent.core.path_safety import looks_like_secret_path, relative_path_is_within


def workspace_files_response(workspace: Path) -> dict[str, Any]:
    files = _git_lines(workspace, ["ls-files", "-co", "--exclude-standard"])
    if files is None:
        files = _walk_workspace_files(workspace)
    return {"files": sorted(path for path in files if path and _safe_surface_path(path) and (workspace / path).is_file())}


def git_status_response(workspace: Path) -> dict[str, Any]:
    if _git_text(workspace, ["rev-parse", "--is-inside-work-tree"]) != "true":
        return {"isRepo": False, "clean": True, "files": [], "diff": "", "diffTruncated": False}
    branch = _git_text(workspace, ["branch", "--show-current"]) or _git_text(workspace, ["rev-parse", "--short", "HEAD"]) or ""
    ahead, behind = _git_ahead_behind(workspace)
    files = [_parse_status_line(line) for line in (_git_lines(workspace, ["status", "--porcelain=v1"]) or [])]
    files = [file for file in files if file is not None]
    safe_files = [file for file in files if _safe_surface_status(file)]
    omitted_files = len(files) - len(safe_files)
    diff_paths = sorted({file["path"] for file in safe_files if file.get("status") != "untracked"})
    diff_parts = [
        _git_text(workspace, ["diff", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", "--", *diff_paths]) if diff_paths else "",
        _git_text(workspace, ["diff", "--cached", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", "--", *diff_paths])
        if diff_paths
        else "",
    ]
    diff = "\n".join(part for part in diff_parts if part).strip()
    limit = 200_000
    truncated = len(diff) > limit
    if truncated:
        diff = diff[:limit]
    return {
        "isRepo": True,
        "branch": branch,
        "ahead": ahead,
        "behind": behind,
        "clean": not files,
        "files": safe_files,
        "diff": diff,
        "diffTruncated": truncated or bool(omitted_files),
        "omittedFiles": omitted_files,
    }


def _git_ahead_behind(workspace: Path) -> tuple[int, int]:
    raw = _git_text(workspace, ["rev-list", "--left-right", "--count", "@{upstream}...HEAD"])
    if not raw:
        return 0, 0
    parts = raw.split()
    if len(parts) != 2:
        return 0, 0
    try:
        behind, ahead = int(parts[0]), int(parts[1])
    except ValueError:
        return 0, 0
    return ahead, behind


def _parse_status_line(line: str) -> dict[str, Any] | None:
    if len(line) < 4:
        return None
    code = line[:2]
    path = line[3:].strip()
    old_path = None
    if " -> " in path:
        old_path, path = path.split(" -> ", 1)
    status = "unknown"
    if "?" in code:
        status = "untracked"
    elif "R" in code:
        status = "renamed"
    elif "C" in code:
        status = "copied"
    elif "A" in code:
        status = "added"
    elif "D" in code:
        status = "deleted"
    elif "T" in code:
        status = "typechange"
    elif "M" in code:
        status = "modified"
    item: dict[str, Any] = {"path": _unquote_git_path(path), "status": status}
    if old_path:
        item["oldPath"] = _unquote_git_path(old_path)
    return item


def _unquote_git_path(path: str) -> str:
    if len(path) >= 2 and path[0] == '"' and path[-1] == '"':
        try:
            return bytes(path[1:-1], "utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            return path[1:-1]
    return path


def _git_lines(workspace: Path, args: list[str]) -> list[str] | None:
    raw = _git_text(workspace, args)
    if raw is None:
        return None
    return [line for line in raw.splitlines() if line]


def _git_text(workspace: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\n")


def _walk_workspace_files(workspace: Path) -> list[str]:
    ignored = {".git", ".tinyagent", "node_modules", "__pycache__", ".venv", "dist", "build"}
    files: list[str] = []
    for path in workspace.rglob("*"):
        try:
            rel = path.relative_to(workspace)
        except ValueError:
            continue
        if any(part in ignored for part in rel.parts):
            continue
        if path.is_file() and _safe_surface_path(rel.as_posix()):
            files.append(rel.as_posix())
        if len(files) >= 5000:
            break
    return files


def _safe_surface_status(file: dict[str, Any]) -> bool:
    path = str(file.get("path") or "")
    old_path = str(file.get("oldPath") or "")
    return _safe_surface_path(path) and (not old_path or _safe_surface_path(old_path))


def _safe_surface_path(path: str) -> bool:
    if not path or looks_like_secret_path(path):
        return False
    if path.startswith(".tinyagent/") or relative_path_is_within(path, ".tinyagent"):
        return False
    return True
