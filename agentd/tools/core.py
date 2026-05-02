"""Shared helpers for local tools."""

from __future__ import annotations

import os
import re
from pathlib import Path

from agentd.output import write_text_artifact
from agentd.state import RunState, ToolCall, ToolResult

SAFE_ENV_KEYS = frozenset(
    {
        "PATH",
        "USER",
        "USERNAME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "SHELL",
    }
)


class ToolError(RuntimeError):
    """Raised when a local tool rejects a request before side effects."""


def resolve_workspace_path(state: RunState, path: str | Path = ".", *, allow_run_artifacts: bool = False) -> Path:
    resolved = state.workspace.resolve_path(path)
    if not state.workspace.contains(resolved):
        raise ToolError(f"Path is outside workspace: {path}")
    if not allow_run_artifacts and is_relative_to(resolved, state.output_dir.resolve()):
        raise ToolError(f"Path is inside current run artifacts: {relative_workspace_path(state, resolved)}")
    return resolved


def relative_workspace_path(state: RunState, path: Path) -> str:
    try:
        return path.resolve().relative_to(state.workspace.root).as_posix()
    except ValueError:
        return str(path)


def combined_output(stdout: str, stderr: str) -> str:
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr


def write_tool_output_artifact(state: RunState, call: ToolCall, prefix: str, output: str, *, kind: str) -> str:
    return write_text_artifact(state, f"{prefix}-{safe_artifact_name(call.id)}.txt", output, kind=kind)


def visible_output(output: str, state: RunState) -> str:
    limit = state.budgets.max_command_output_chars_visible
    if len(output) <= limit:
        return output
    marker = "\n[truncated]"
    if limit <= len(marker):
        return output[:limit]
    return output[: limit - len(marker)] + marker


def safe_artifact_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "call")


def tool_env(state: RunState) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
    home = state.output_dir / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def error_result(tool_name: str, call: ToolCall, exc: Exception) -> ToolResult:
    return ToolResult(tool_name=tool_name, call_id=call.id, output=str(exc), ok=False, data={"error_type": type(exc).__name__})


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
