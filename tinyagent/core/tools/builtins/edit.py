"""Alternative edit adapters for non-OpenAI-style models."""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from tinyagent.core.contracts import ToolRuntime
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.tools.core import capture_tool_output, duration_ms, error_result, relative_workspace_path, resolve_workspace_path

MAX_WRITE_FILE_BYTES = 128_000


@dataclass(frozen=True)
class _FileSnapshot:
    existed: bool
    data: bytes | None = None


class StrReplaceEditTool:
    name = "str_replace_edit"
    runtime = ToolRuntime(parallel_safe=False, mutates_workspace=True, lock_key="workspace")
    schema = {
        "name": "str_replace_edit",
        "description": "Edit one workspace file by replacing a unique old_str with new_str.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_str": {"type": "string"},
                "new_str": {"type": "string"},
            },
            "required": ["path", "old_str", "new_str"],
        },
    }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        started = time.monotonic()
        try:
            path = resolve_workspace_path(state, call.args["path"])
            old = str(call.args["old_str"])
            new = str(call.args["new_str"])
            if not old:
                raise ValueError("old_str is required")
            before = path.read_text()
            count = before.count(old)
            if count != 1:
                raise ValueError(f"old_str must match exactly once; found {count}")
            _atomic_write_text(path, before.replace(old, new, 1))
            rel = relative_workspace_path(state, path)
            output = f"Updated {rel} with str_replace_edit.\n"
            return _edit_result(self.name, call, state, output, True, [rel], started)
        except Exception as exc:
            return error_result(self.name, call, exc)


class WriteFileTool:
    name = "write_file"
    runtime = ToolRuntime(parallel_safe=False, mutates_workspace=True, lock_key="workspace")
    schema = {
        "name": "write_file",
        "description": "Overwrite one small workspace file with full content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        started = time.monotonic()
        try:
            path = resolve_workspace_path(state, call.args["path"])
            content = str(call.args["content"])
            if len(content.encode()) > MAX_WRITE_FILE_BYTES:
                raise ValueError(f"write_file content exceeds {MAX_WRITE_FILE_BYTES} bytes")
            _atomic_write_text(path, content)
            rel = relative_workspace_path(state, path)
            output = f"Wrote {rel} with write_file.\n"
            return _edit_result(self.name, call, state, output, True, [rel], started)
        except Exception as exc:
            return error_result(self.name, call, exc)


def _edit_result(
    tool_name: str,
    call: ToolCall,
    state: RunState,
    output: str,
    ok: bool,
    paths: list[str],
    started: float,
) -> ToolResult:
    captured = capture_tool_output(state, call, output, prefix="edit-output", kind="edit_output")
    elapsed_ms = duration_ms(started)
    state.emit(
        "file.edited",
        {
            "tool_call_id": call.id,
            "tool": tool_name,
            "paths": paths,
            "ok": ok,
            **captured.data,
            "duration_ms": elapsed_ms,
        },
    )
    return captured.tool_result(
        tool_name,
        call,
        ok=ok,
        duration_ms=elapsed_ms,
        summary=output.strip(),
        data={
            "paths": paths,
            **captured.data,
            "duration_ms": elapsed_ms,
        },
        metadata={"paths": paths},
        failure=not ok,
    )


def _snapshot(path: Path) -> _FileSnapshot:
    if not path.exists():
        return _FileSnapshot(existed=False)
    if not path.is_file():
        raise ValueError(f"Edit path is not a regular file: {path}")
    return _FileSnapshot(existed=True, data=path.read_bytes())


def _restore(path: Path, snapshot: _FileSnapshot) -> None:
    if snapshot.existed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(snapshot.data or b"")
    elif path.exists():
        path.unlink()


def _atomic_write_text(path: Path, content: str) -> None:
    snapshot = _snapshot(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as temp:
            temp_name = temp.name
            temp.write(content)
        os.replace(temp_name, path)
    except Exception:
        if temp_name:
            try:
                Path(temp_name).unlink()
            except OSError:
                pass
        _restore(path, snapshot)
        raise
