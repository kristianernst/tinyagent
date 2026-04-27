#!/usr/bin/env python3
"""Print a small LOC report for Tinyagent's core files."""

from __future__ import annotations

import argparse
from pathlib import Path

DEFAULT_PATHS = [
    "agentd/kernel.py",
    "agentd/state.py",
    "agentd/events.py",
    "agentd/model_stream.py",
    "agentd/models.py",
    "agentd/providers/openai_compat.py",
    "agentd/context.py",
    "agentd/output.py",
    "agentd/tools.py",
    "agentd/tool_core.py",
    "agentd/builtins/shell.py",
    "agentd/builtins/patch.py",
    "agentd/tools_repo.py",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=DEFAULT_PATHS, help="Files to include in the report.")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root.")
    args = parser.parse_args()

    rows = [_row(args.root / path, path) for path in args.paths]
    width = max(len(label) for label, _ in rows)
    total = sum(lines for _, lines in rows)
    for label, lines in rows:
        print(f"{label:<{width}} {lines:>5} LOC")
    print(f"{'total':<{width}} {total:>5} LOC")
    return 0


def _row(path: Path, label: str) -> tuple[str, int]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return label, 0
    return label, len(lines)


if __name__ == "__main__":
    raise SystemExit(main())
