"""Optional repo inspection tools."""

from __future__ import annotations

from pathlib import Path

from tinyagent.core.contextfs import model_readable_path, read_hints, write_context_tool_output
from tinyagent.core.contracts import Tool, ToolRuntime
from tinyagent.core.index.safety import EXCLUDED_INDEX_DIRS, MAX_INDEX_FILE_BYTES, is_excluded_index_path
from tinyagent.core.path_safety import resolved_relative_to
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.token_utils import estimate_tokens, fits_token_budget
from tinyagent.core.tools.core import (
    error_result,
    relative_workspace_path,
    resolve_workspace_path,
    visible_output,
)

EXCLUDED_SEARCH_DIRS = EXCLUDED_INDEX_DIRS
MAX_READ_FILE_BYTES = MAX_INDEX_FILE_BYTES


class ReadFileTool:
    name = "read_file"
    runtime = ToolRuntime(parallel_safe=True)
    schema = {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "max_lines": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        },
    }

    def __init__(self, *, allow_run_artifacts: bool = False) -> None:
        self.allow_run_artifacts = allow_run_artifacts

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        try:
            path = resolve_workspace_path(state, call.args["path"], allow_run_artifacts=self.allow_run_artifacts)
            start_line = max(int(call.args.get("start_line", 1)), 1)
            max_lines = max(int(call.args.get("max_lines", 400)), 1)
            file_size = path.stat().st_size
            if file_size > MAX_READ_FILE_BYTES:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call.id,
                    output=f"file is too large to read: {relative_workspace_path(state, path)} ({file_size} bytes)",
                    ok=False,
                    data={"path": relative_workspace_path(state, path), "bytes": file_size, "max_bytes": MAX_READ_FILE_BYTES},
                )
            text = path.read_text(errors="replace")
        except Exception as exc:
            return error_result(self.name, call, exc)

        lines = text.splitlines()
        selected = lines[start_line - 1 : start_line - 1 + max_lines]
        numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(selected, start=start_line))
        rel_path = relative_workspace_path(state, path)
        complete_file = start_line == 1 and len(selected) == len(lines)
        shown_line_end = start_line + max(len(selected) - 1, 0)
        output = f"{rel_path}\n{numbered}" if numbered else f"{rel_path}\n"
        output_tokens = estimate_tokens(output)
        artifact_path = None
        hints: list[str] = []
        if not fits_token_budget(output, state.budgets.max_tool_output_tokens_visible):
            artifact_path = write_context_tool_output(state, call, output, kind="read_file_output")
            hints = read_hints(model_readable_path(state, artifact_path))
            output = visible_output(output, state)
        state.emit(
            "file.read",
            {
                "path": rel_path,
                "start_line": start_line,
                "line_count": len(selected),
                "total_lines": len(lines),
                "bytes": len(text.encode()),
                "output_tokens": output_tokens,
                "context_artifact": artifact_path,
                "complete_file": complete_file and artifact_path is None,
                "shown_line_start": start_line,
                "shown_line_end": shown_line_end,
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=output,
            data={
                "path": rel_path,
                "start_line": start_line,
                "line_count": len(selected),
                "total_lines": len(lines),
                "bytes": len(text.encode()),
                "context_artifact": artifact_path,
                "output_tokens": output_tokens,
                "complete_file": complete_file and artifact_path is None,
                "shown_line_start": start_line,
                "shown_line_end": shown_line_end,
            },
            artifact_path=artifact_path,
            truncated=artifact_path is not None,
            read_hints=hints,
        )


class ListFilesTool:
    name = "list_files"
    runtime = ToolRuntime(parallel_safe=True)
    schema = {
        "name": "list_files",
        "description": "List files inside the workspace, excluding trace and git directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 1},
            },
        },
    }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        try:
            root = resolve_workspace_path(state, call.args.get("path", "."), allow_run_artifacts=True)
            max_files = max(int(call.args.get("max_files", 200)), 1)
            files = list(_iter_workspace_files(state, root, max_files=max_files + 1))
        except Exception as exc:
            return error_result(self.name, call, exc)

        truncated = len(files) > max_files
        visible = files[:max_files]
        output = "\n".join(relative_workspace_path(state, path) for path in visible)
        state.emit(
            "files.listed",
            {
                "path": relative_workspace_path(state, root),
                "file_count": len(visible),
                "truncated": truncated,
                "excluded": _excluded_search_labels(state),
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=output,
            data={"file_count": len(visible), "truncated": truncated},
        )


def repo_inspect_tools() -> list[Tool]:
    return [ReadFileTool(), ListFilesTool()]


def _iter_workspace_files(state: RunState, root: Path, *, max_files: int) -> list[Path]:
    if root.is_file():
        return [root] if not _excluded(state, root) else []
    if _excluded(state, root):
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if path.is_file() and not _excluded(state, path):
            files.append(path)
    return files


def _excluded(state: RunState, path: Path) -> bool:
    resolved = path.resolve()
    if resolved_relative_to(resolved, state.workspace.root) is None:
        return True
    if is_excluded_index_path(state.workspace.root, resolved):
        return True
    return _output_dir_inside_workspace(state) is not None and resolved_relative_to(resolved, state.output_dir) is not None


def _excluded_search_labels(state: RunState) -> list[str]:
    excluded = set(EXCLUDED_SEARCH_DIRS)
    relative = _output_dir_inside_workspace(state)
    if relative is not None:
        excluded.add(relative)
    return sorted(excluded)


def _output_dir_inside_workspace(state: RunState) -> str | None:
    relative = resolved_relative_to(state.output_dir, state.workspace.root)
    return relative.as_posix() if relative is not None else None
