#!/usr/bin/env python3
"""Print a grouped LOC report for Tinyagent."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

CODE_SUFFIXES = {
    ".css",
    ".html",
    ".js",
    ".md",
    ".py",
    ".ts",
    ".tsx",
}
EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tinyagent",
    ".venv",
    "dist",
    "node_modules",
    "__pycache__",
}
STRICT_CORE_PREFIXES = (
    "tinyagent/core/context/",
    "tinyagent/core/providers/",
    "tinyagent/core/tools/",
)
STRICT_CORE_FILES = {
    "tinyagent/__init__.py",
    "tinyagent/core/__init__.py",
    "tinyagent/core/config.py",
    "tinyagent/core/container_sandbox.py",
    "tinyagent/core/contextfs.py",
    "tinyagent/core/contracts.py",
    "tinyagent/core/events.py",
    "tinyagent/core/execution.py",
    "tinyagent/core/extensions.py",
    "tinyagent/core/hooks.py",
    "tinyagent/core/ids.py",
    "tinyagent/core/kernel.py",
    "tinyagent/core/model_stream.py",
    "tinyagent/core/models.py",
    "tinyagent/core/observations.py",
    "tinyagent/core/output.py",
    "tinyagent/core/policy.py",
    "tinyagent/core/profiles.py",
    "tinyagent/core/progress.py",
    "tinyagent/core/run_control.py",
    "tinyagent/core/sdk.py",
    "tinyagent/core/state.py",
    "tinyagent/core/transcript.py",
    "tinyagent/core/workspace.py",
    "tinyagent/core/workspace_delta.py",
}
APP_RUNTIME_FILES = {
    "tinyagent/app/__init__.py",
    "tinyagent/app/product.py",
    "tinyagent/app/server.py",
}
EVAL_FILES = {
    "tinyagent/evals/metrics.py",
    "tinyagent/evals/runner.py",
    "tinyagent/evals/__init__.py",
}
RUNTIME_FILES = {
    "tinyagent/runtime/__init__.py",
    "tinyagent/runtime/conversation.py",
    "tinyagent/runtime/replay.py",
    "tinyagent/runtime/run_graph.py",
    "tinyagent/runtime/run_record.py",
    "tinyagent/runtime/server.py",
}


@dataclass(frozen=True)
class FileStat:
    path: str
    loc: int


@dataclass(frozen=True)
class GroupStat:
    name: str
    files: list[FileStat]

    @property
    def loc(self) -> int:
        return sum(file.loc for file in self.files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--files", action="store_true", help="Include per-file rows under each group.")
    args = parser.parse_args()

    groups = _group_stats(args.root)
    if args.json:
        print(
            json.dumps(
                {
                    "groups": [
                        {
                            "name": group.name,
                            "loc": group.loc,
                            "files": [{"path": file.path, "loc": file.loc} for file in group.files],
                        }
                        for group in groups
                    ],
                    "total": sum(group.loc for group in groups),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    width = max(len(group.name) for group in groups)
    total = sum(group.loc for group in groups)
    for group in groups:
        print(f"{group.name:<{width}} {group.loc:>6} LOC {len(group.files):>4} files")
        if args.files:
            for file in sorted(group.files, key=lambda item: item.path):
                print(f"  {file.path:<70} {file.loc:>6}")
    print(f"{'total':<{width}} {total:>6} LOC")
    return 0


def _group_stats(root: Path) -> list[GroupStat]:
    buckets: dict[str, list[FileStat]] = {
        "tinyagent-core": [],
        "tinyagent-runtime": [],
        "tinyagent-app": [],
        "tinyagent-cli": [],
        "tinyagent-evals": [],
        "chatui": [],
        "tests": [],
        "docs": [],
        "repo-scripts": [],
        "other": [],
    }
    for path in _iter_source_files(root):
        rel = path.relative_to(root).as_posix()
        buckets[_group_for(rel)].append(FileStat(rel, _loc(path)))
    return [GroupStat(name, files) for name, files in buckets.items() if files]


def _iter_source_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue
        if path.suffix not in CODE_SUFFIXES:
            continue
        yield path


def _group_for(path: str) -> str:
    if path in APP_RUNTIME_FILES:
        return "tinyagent-app"
    if path in EVAL_FILES:
        return "tinyagent-evals"
    if path in RUNTIME_FILES:
        return "tinyagent-runtime"
    if path in STRICT_CORE_FILES or path.startswith(STRICT_CORE_PREFIXES):
        return "tinyagent-core"
    if path == "tinyagent/cli.py":
        return "tinyagent-cli"
    if path.startswith("chatui/"):
        return "chatui"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("docs/"):
        return "docs"
    if path.startswith("scripts/"):
        return "repo-scripts"
    return "other"


def _loc(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except UnicodeDecodeError:
        return sum(1 for line in path.read_text(errors="ignore").splitlines() if line.strip())


if __name__ == "__main__":
    raise SystemExit(main())
