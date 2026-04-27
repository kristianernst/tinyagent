"""Optional repo inspection tools."""

from __future__ import annotations

import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path

from agentd.contracts import Tool
from agentd.state import RunState, ToolCall, ToolResult
from agentd.tool_core import (
    error_result,
    is_relative_to,
    relative_workspace_path,
    resolve_workspace_path,
    tool_env,
    write_tool_output_artifact,
)

EXCLUDED_SEARCH_DIRS = frozenset({".git", ".tinyagent"})
MAX_READ_FILE_BYTES = 1_000_000


class ReadFileTool:
    name = "read_file"
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
        state.add_event(
            "FileRead",
            {
                "path": rel_path,
                "start_line": start_line,
                "line_count": len(selected),
                "total_lines": len(lines),
                "bytes": len(text.encode()),
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=f"{rel_path}\n{numbered}" if numbered else f"{rel_path}\n",
            data={"path": rel_path, "line_count": len(selected), "total_lines": len(lines)},
        )


class ListFilesTool:
    name = "list_files"
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
        state.add_event(
            "FilesListed",
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


class SearchRepoTool:
    name = "search_repo"
    schema = {
        "name": "search_repo",
        "description": "Search text inside workspace files, excluding trace and git directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "max_matches": {"type": "integer", "minimum": 1},
            },
            "required": ["query"],
        },
    }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        query = str(call.args.get("query", ""))
        if not query:
            return ToolResult(tool_name=self.name, call_id=call.id, output="query is required", ok=False)
        try:
            path = resolve_workspace_path(state, call.args.get("path", "."), allow_run_artifacts=True)
            max_matches = max(int(call.args.get("max_matches", 100)), 1)
        except Exception as exc:
            return error_result(self.name, call, exc)

        try:
            output, captured_output, match_count, truncated, used_rg, timed_out = _search_workspace(
                state,
                path,
                query,
                max_matches=max_matches,
            )
        except Exception as exc:
            return error_result(self.name, call, exc)
        artifact = write_tool_output_artifact(
            state,
            call,
            "search-output",
            captured_output or "No matches.",
            kind="search_captured_output",
        )
        state.add_event(
            "SearchCompleted",
            {
                "query": query,
                "path": relative_workspace_path(state, path),
                "match_count": match_count,
                "truncated": truncated,
                "timed_out": timed_out,
                "used_rg": used_rg,
                "excluded": _excluded_search_labels(state),
                "captured_output_artifact": artifact,
                "captured_output_chars": len(captured_output or "No matches."),
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=output or "No matches.",
            data={
                "query": query,
                "path": relative_workspace_path(state, path),
                "match_count": match_count,
                "truncated": truncated,
                "timed_out": timed_out,
                "used_rg": used_rg,
                "captured_output_artifact": artifact,
                "captured_output_chars": len(captured_output or "No matches."),
                "output_artifact": artifact,
                "output_chars": len(captured_output or "No matches."),
            },
        )


def repo_inspect_tools() -> list[Tool]:
    return [ReadFileTool(), ListFilesTool(), SearchRepoTool()]


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


def _search_workspace(state: RunState, path: Path, query: str, *, max_matches: int) -> tuple[str, str, int, bool, bool, bool]:
    if _excluded(state, path):
        return "", "", 0, False, False, False

    rg = shutil.which("rg")
    if rg is not None:
        target = relative_workspace_path(state, path)
        lines, truncated, timed_out = _run_rg_limited(state, rg, query, target, max_matches=max_matches)
        visible = lines[:max_matches]
        captured_output = "\n".join(lines)
        return "\n".join(visible), captured_output, len(visible), truncated, True, timed_out

    matches: list[str] = []
    deadline = time.monotonic() + max(state.budgets.max_shell_timeout_seconds, 1)
    for file_path in _iter_workspace_files(state, path, max_files=100_000):
        if time.monotonic() >= deadline:
            return "\n".join(matches[:max_matches]), "\n".join(matches), min(len(matches), max_matches), True, False, True
        try:
            if file_path.stat().st_size > MAX_READ_FILE_BYTES:
                continue
            text = file_path.read_text(errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                matches.append(f"{relative_workspace_path(state, file_path)}:{line_number}:{line}")
                if len(matches) >= max_matches + 1:
                    return "\n".join(matches[:max_matches]), "\n".join(matches), max_matches, True, False, False
    output = "\n".join(matches)
    return output, output, len(matches), False, False, False


def _run_rg_limited(state: RunState, rg: str, query: str, target: str, *, max_matches: int) -> tuple[list[str], bool, bool]:
    command = [
        rg,
        "--line-number",
        "--no-heading",
        "--color",
        "never",
        "--max-filesize",
        "2M",
        "--max-columns",
        "300",
        "--glob",
        "!**/.tinyagent/**",
        "--glob",
        "!**/.git/**",
    ]
    command.extend(_rg_exclude_output_dir_args(state))
    command.extend(["--", query, target])
    process = subprocess.Popen(
        command,
        cwd=state.workspace.root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=tool_env(state),
    )
    assert process.stdout is not None
    lines: list[str] = []
    truncated = False
    timed_out = False
    buffer = b""
    deadline = time.monotonic() + max(state.budgets.max_shell_timeout_seconds, 1)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                truncated = True
                process.terminate()
                break
            events = selector.select(timeout=min(0.1, remaining))
            if not events:
                continue
            chunk = os.read(process.stdout.fileno(), 8192)
            if not chunk:
                break
            buffer = _append_rg_chunk(buffer, chunk, lines)
            if len(lines) > max_matches:
                truncated = True
                process.terminate()
                break
        while not timed_out and len(lines) <= max_matches:
            chunk = os.read(process.stdout.fileno(), 8192)
            if not chunk:
                break
            buffer = _append_rg_chunk(buffer, chunk, lines)
        if buffer and len(lines) <= max_matches:
            lines.append(buffer.decode(errors="replace").rstrip("\r"))
        if len(lines) > max_matches:
            truncated = True
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
    finally:
        selector.close()
        process.stdout.close()
    return lines, truncated, timed_out


def _append_rg_chunk(buffer: bytes, chunk: bytes, lines: list[str]) -> bytes:
    buffer += chunk
    while b"\n" in buffer:
        raw_line, buffer = buffer.split(b"\n", 1)
        lines.append(raw_line.decode(errors="replace").rstrip("\r"))
    return buffer


def _excluded(state: RunState, path: Path) -> bool:
    try:
        resolved = path.resolve()
        parts = resolved.relative_to(state.workspace.root).parts
    except ValueError:
        return True
    if any(part in EXCLUDED_SEARCH_DIRS for part in parts):
        return True
    return _output_dir_inside_workspace(state) is not None and is_relative_to(resolved, state.output_dir.resolve())


def _rg_exclude_output_dir_args(state: RunState) -> list[str]:
    relative = _output_dir_inside_workspace(state)
    if relative is None:
        return []
    return ["--glob", f"!{relative}", "--glob", f"!{relative}/**"]


def _excluded_search_labels(state: RunState) -> list[str]:
    excluded = set(EXCLUDED_SEARCH_DIRS)
    relative = _output_dir_inside_workspace(state)
    if relative is not None:
        excluded.add(relative)
    return sorted(excluded)


def _output_dir_inside_workspace(state: RunState) -> str | None:
    try:
        return state.output_dir.resolve().relative_to(state.workspace.root).as_posix()
    except ValueError:
        return None
