"""Project instruction loading for model-visible context."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from tinyagent.core.context.types import ContextConfig, ProjectInstructions
from tinyagent.core.token_utils import estimate_tokens, token_budget_to_text_limit

PROJECT_INSTRUCTION_FILE = "AGENTS.md"


def load_project_instructions(workspace_root: Path, config: ContextConfig | None = None) -> ProjectInstructions:
    config = config or ContextConfig()
    paths = _instruction_paths(workspace_root)
    chunks: list[str] = []
    files: list[str] = []
    remaining_tokens = max(config.project_instruction_max_tokens, 0)
    truncated = False

    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        chunk = f"## {path}\n\n{text.strip()}\n"
        files.append(str(path))
        if remaining_tokens <= 0:
            truncated = True
            continue
        chunk_tokens = estimate_tokens(chunk)
        if chunk_tokens > remaining_tokens:
            chunks.append(chunk[: token_budget_to_text_limit(remaining_tokens)].rstrip())
            truncated = True
            remaining_tokens = 0
            continue
        chunks.append(chunk.rstrip())
        remaining_tokens -= chunk_tokens

    return ProjectInstructions(content="\n\n".join(chunks), files=tuple(files), truncated=truncated)


def _instruction_paths(workspace_root: Path) -> list[Path]:
    root = workspace_root.expanduser().resolve()
    paths = [Path.home() / ".tinyagent" / PROJECT_INSTRUCTION_FILE]
    git_root = _git_root(root) or root
    try:
        relative = root.relative_to(git_root)
    except ValueError:
        git_root = root
        relative = Path()
    current = git_root
    paths.append(current / PROJECT_INSTRUCTION_FILE)
    for part in relative.parts:
        current = current / part
        paths.append(current / PROJECT_INSTRUCTION_FILE)
    return _dedupe_paths(paths)


def _git_root(root: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return Path(value).resolve() if value else None


def _dedupe_paths(paths: Sequence[Path]) -> list[Path]:
    output: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        output.append(resolved)
    return output
