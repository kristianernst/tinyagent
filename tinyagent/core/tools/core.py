"""Shared helpers for local tools."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tinyagent.core.contextfs import model_readable_path, read_hints, write_context_tool_output
from tinyagent.core.output import write_text_artifact
from tinyagent.core.path_safety import is_env_file_name, resolved_relative_to, safe_artifact_name
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.token_utils import clip_text_to_token_budget, estimate_tokens

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


@dataclass(frozen=True)
class ToolOutputCapture:
    output_artifact: str
    context_artifact: str
    context_read_path: str
    preview: str
    output_tokens: int

    @property
    def data(self) -> dict[str, object]:
        return {
            "output_artifact": self.output_artifact,
            "context_artifact": self.context_artifact,
            "output_tokens": self.output_tokens,
        }

    @property
    def truncated(self) -> bool:
        return self.output_tokens > estimate_tokens(self.preview)

    def read_hints(self, *, failure: bool = False) -> list[str]:
        return read_hints(self.context_read_path, failure=failure)

    def tool_result(
        self,
        tool_name: str,
        call: ToolCall,
        *,
        ok: bool,
        duration_ms: int,
        summary: str,
        data: dict[str, Any],
        failure: bool,
        failure_kind: str | None = None,
        exit_code: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        return ToolResult(
            tool_name=tool_name,
            call_id=call.id,
            output=self.preview,
            ok=ok,
            exit_code=exit_code,
            duration_ms=duration_ms,
            summary=summary,
            content_preview=self.preview,
            artifact_path=self.context_artifact,
            truncated=self.truncated,
            failure_kind=failure_kind,
            data=data,
            metadata=metadata or {},
            read_hints=self.read_hints(failure=failure),
        )


def resolve_workspace_path(state: RunState, path: str | Path = ".", *, allow_run_artifacts: bool = False) -> Path:
    resolved = state.workspace.resolve_path(path)
    if not state.workspace.contains(resolved):
        raise ToolError(f"Path is outside workspace: {path}")
    if not allow_run_artifacts and _is_env_path(state, resolved):
        raise ToolError(f"Path is protected environment file: {relative_workspace_path(state, resolved)}")
    if not allow_run_artifacts and resolved_relative_to(resolved, state.output_dir) is not None:
        raise ToolError(f"Path is inside current run artifacts: {relative_workspace_path(state, resolved)}")
    if not allow_run_artifacts and _is_workspace_tinyagent_path(state, resolved):
        raise ToolError(f"Path is inside protected .tinyagent evidence: {relative_workspace_path(state, resolved)}")
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


def capture_tool_output(
    state: RunState,
    call: ToolCall,
    output: str,
    *,
    prefix: str,
    kind: str,
    context_kind: str | None = None,
) -> ToolOutputCapture:
    output_artifact = write_text_artifact(state, f"{prefix}-{safe_artifact_name(call.id)}.txt", output, kind=kind)
    context_artifact = write_context_tool_output(state, call, output, kind=context_kind or kind)
    return ToolOutputCapture(
        output_artifact=output_artifact,
        context_artifact=context_artifact,
        context_read_path=model_readable_path(state, context_artifact),
        preview=visible_output(output, state),
        output_tokens=estimate_tokens(output),
    )


def visible_output(output: str, state: RunState) -> str:
    return clip_text_to_token_budget(output, state.budgets.max_tool_output_tokens_visible)


def tool_env(state: RunState) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
    home = state.output_dir / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def duration_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def error_result(tool_name: str, call: ToolCall, exc: Exception) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        call_id=call.id,
        output=str(exc),
        ok=False,
        data={"error_type": type(exc).__name__, "failure_kind": "invalid_tool_args"},
        failure_kind="invalid_tool_args",
        summary=str(exc),
        content_preview=str(exc),
    )


def _is_workspace_tinyagent_path(state: RunState, path: Path) -> bool:
    relative = resolved_relative_to(path, state.workspace.root)
    return relative is not None and bool(relative.parts and relative.parts[0] == ".tinyagent")


def _is_env_path(state: RunState, path: Path) -> bool:
    relative = resolved_relative_to(path, state.workspace.root)
    return relative is not None and bool(relative.parts and is_env_file_name(relative.parts[-1]))
