"""Shared workspace-index path and exclusion helpers."""

from __future__ import annotations

import re
from pathlib import Path

from tinyagent.core.path_safety import SECRET_DIR_NAMES, SECRET_FILE_NAMES, looks_like_secret_path

MAX_INDEX_FILE_BYTES = 1_000_000
EXCLUDED_INDEX_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".tinyagent",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        *SECRET_DIR_NAMES,
    }
)
LINE_FRAGMENT_RE = re.compile(r"^L(?P<line>[1-9][0-9]*)$")


def parse_code_ref(ref: str) -> tuple[str, int | None]:
    path_text = ref.removeprefix("code:")
    path_part, _sep, fragment = path_text.partition("#")
    line = _line_fragment(fragment)
    return path_part, line


def is_excluded_index_path(root: Path, path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        return True
    if any(part in EXCLUDED_INDEX_DIRS for part in relative.parts):
        return True
    return looks_like_secret_path(relative)


def assert_index_file_readable(root: Path, path: Path, *, ref: str) -> None:
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    try:
        path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"Index ref outside workspace: {ref}") from exc
    if is_excluded_index_path(root_resolved, path_resolved):
        raise PermissionError(f"Index ref is excluded: {ref}")
    if not path_resolved.is_file():
        raise KeyError(ref)
    size = path_resolved.stat().st_size
    if size > MAX_INDEX_FILE_BYTES:
        raise ValueError(f"Index ref is too large: {ref} ({size} bytes)")


def rg_exclude_globs() -> list[str]:
    globs: list[str] = []
    for name in sorted(EXCLUDED_INDEX_DIRS):
        globs.extend(["--glob", f"!**/{name}/**"])
    for name in sorted(SECRET_FILE_NAMES):
        globs.extend(["--glob", f"!**/{name}"])
    globs.extend(["--glob", "!**/.env*"])
    return globs


def _line_fragment(fragment: str) -> int | None:
    if not fragment:
        return None
    match = LINE_FRAGMENT_RE.match(fragment)
    if match is None:
        return None
    return int(match.group("line"))
