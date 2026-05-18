"""Diff rendering helpers shared by runtime trace surfaces."""

from __future__ import annotations

import difflib
from pathlib import Path

MAX_UNTRACKED_DIFF_BYTES = 1_000_000


def new_file_patch(path: Path, relative_path: str) -> str:
    body = "\n".join(new_file_diff_lines(path, display_path=f"b/{relative_path}"))
    if not body:
        return ""
    header = f"diff --git a/{relative_path} b/{relative_path}\nnew file mode 100644\nindex 0000000..0000000\n"
    return header + body + "\n"


def new_file_diff_lines(path: Path, *, display_path: str) -> list[str]:
    if path.is_symlink():
        return []
    try:
        size = path.stat().st_size
    except OSError:
        return []
    if size > MAX_UNTRACKED_DIFF_BYTES:
        return [f"Binary files /dev/null and {display_path} differ"]
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    if b"\0" in raw:
        return [f"Binary files /dev/null and {display_path} differ"]
    text = raw.decode(errors="replace").splitlines()
    return list(difflib.unified_diff([], text, fromfile="/dev/null", tofile=display_path, lineterm=""))


def join_diff_parts(*parts: str) -> str:
    output = ""
    for part in parts:
        if not part:
            continue
        if output and not output.endswith("\n"):
            output += "\n"
        output += part
    return output
