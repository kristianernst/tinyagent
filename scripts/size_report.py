#!/usr/bin/env python3
"""Print a grouped LOC report or export source context for Tinyagent."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
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
EXPORT_SUFFIXES = {".py"}
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
CORE_PREFIXES = ("tinyagent/core/", "tinyagent/extensions/")
APP_PREFIXES = ("tinyagent/app/",)
EVAL_PREFIXES = ("tinyagent/evals/",)
RUNTIME_PREFIXES = ("tinyagent/runtime/",)


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
    parser.add_argument("--export", type=Path, help="Write a Markdown source export instead of printing a LOC report.")
    parser.add_argument("--source-root", default="tinyagent", help="Source directory to export with --export.")
    args = parser.parse_args()

    root = args.root.resolve()
    if args.export:
        output = (root / args.export).resolve()
        source_root = (root / args.source_root).resolve()
        if not source_root.is_dir():
            raise SystemExit(f"source root does not exist: {source_root}")
        groups = _group_stats(root, exclude={_display_path(root, output)})
        files = list(_iter_export_files(source_root))
        rendered = _render_export(root, source_root, files, groups)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote {_display_path(root, output)} with {len(files)} files and about {_estimate_tokens(rendered)} tokens")
        return 0

    groups = _group_stats(root)
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


def _group_stats(root: Path, *, exclude: set[str] | None = None) -> list[GroupStat]:
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
    for path in _iter_source_files(root, exclude=exclude or set()):
        rel = path.relative_to(root).as_posix()
        buckets[_group_for(rel)].append(FileStat(rel, _loc(path)))
    return [GroupStat(name, files) for name, files in buckets.items() if files]


def _iter_source_files(root: Path, *, exclude: set[str]):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        rel_path = rel.as_posix()
        rel_parts = rel.parts
        if rel_path in exclude:
            continue
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue
        if path.suffix not in CODE_SUFFIXES:
            continue
        yield path


def _iter_export_files(source_root: Path) -> list[Path]:
    return sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix in EXPORT_SUFFIXES and not any(part in EXCLUDED_DIRS for part in path.parts)
    )


def _group_for(path: str) -> str:
    if path.startswith(CORE_PREFIXES):
        return "tinyagent-core"
    if path.startswith(RUNTIME_PREFIXES):
        return "tinyagent-runtime"
    if path.startswith(APP_PREFIXES):
        return "tinyagent-app"
    if path.startswith(EVAL_PREFIXES):
        return "tinyagent-evals"
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


def _render_export(root: Path, source_root: Path, files: list[Path], groups: list[GroupStat]) -> str:
    body = _render_export_body(root, files, groups)
    export_date = datetime.now().astimezone().isoformat(timespec="seconds")
    token_count = 0
    rendered = ""
    for _ in range(3):
        rendered = "\n".join(
            [
                "---",
                f'export_date: "{export_date}"',
                f'source_root: "{source_root.relative_to(root).as_posix()}"',
                f"file_count: {len(files)}",
                f"source_loc: {sum(_loc(path) for path in files)}",
                f"total_loc: {sum(group.loc for group in groups)}",
                f"approx_token_count: {token_count}",
                'token_estimator: "characters / 4"',
                "---",
                "",
                body,
            ]
        )
        next_token_count = _estimate_tokens(rendered)
        if next_token_count == token_count:
            break
        token_count = next_token_count
    return rendered


def _render_export_body(root: Path, files: list[Path], groups: list[GroupStat]) -> str:
    lines = [
        "# Tinyagent Code Export",
        "",
        "## Size Report",
        "",
        "| Group | LOC | Files |",
        "| --- | ---: | ---: |",
        *[f"| {group.name} | {group.loc} | {len(group.files)} |" for group in groups],
        f"| total | {sum(group.loc for group in groups)} | {sum(len(group.files) for group in groups)} |",
        "",
        "Generated by `scripts/size_report.py --export`.",
        "",
    ]
    for path in files:
        relative = path.relative_to(root).as_posix()
        lines.extend(
            [
                f"## `{relative}`",
                "",
                f"```{_language_for(path)}",
                path.read_text(encoding="utf-8").rstrip(),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def _language_for(path: Path) -> str:
    return "python" if path.suffix == ".py" else ""


def _display_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


if __name__ == "__main__":
    raise SystemExit(main())
