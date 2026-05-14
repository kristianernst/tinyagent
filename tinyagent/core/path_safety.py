"""Shared path-safety predicates for workspace-visible surfaces."""

from __future__ import annotations

import re
from pathlib import Path

SECRET_DIR_NAMES = frozenset({".ssh"})
SECRET_FILE_NAMES = frozenset({".env", ".npmrc", ".pypirc", ".netrc"})
SECRET_PATH_NAMES = SECRET_DIR_NAMES | SECRET_FILE_NAMES


def checked_relative_path(value: str | Path, *, label: str = "Path") -> Path:
    path = Path(value)
    if not path.parts or path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{label} must be a relative path without parent traversal: {value}")
    return path


def relative_path_is_within(path: str | Path, parent: str | Path) -> bool:
    parent_text = Path(parent).as_posix()
    path_text = Path(path).as_posix()
    return parent_text in {"", "."} or path_text == parent_text or path_text.startswith(f"{parent_text}/")


def resolved_relative_to(path: str | Path, root: str | Path) -> Path | None:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return None


def is_env_file_name(name: str) -> bool:
    return name == ".env" or name.startswith(".env.")


def looks_like_env_path(path: str | Path) -> bool:
    return any(is_env_file_name(part) for part in Path(path).parts)


def looks_like_secret_path(path: str | Path) -> bool:
    return any(part in SECRET_PATH_NAMES or is_env_file_name(part) for part in Path(path).parts)


def safe_artifact_name(value: str | None) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "call")
    return "call" if name in {"", ".", ".."} else name
