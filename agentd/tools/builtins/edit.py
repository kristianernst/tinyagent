"""Alternative edit adapters for non-OpenAI-style models."""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from agentd.contextfs import model_readable_path, read_hints, write_context_tool_output
from agentd.state import RunState, ToolCall, ToolResult
from agentd.tools.core import error_result, relative_workspace_path, resolve_workspace_path, visible_output, write_tool_output_artifact

MAX_WRITE_FILE_BYTES = 128_000


@dataclass(frozen=True)
class _FileSnapshot:
    existed: bool
    data: bytes | None = None


class StrReplaceEditTool:
    name = "str_replace_edit"
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
    artifact = write_tool_output_artifact(state, call, "edit-output", output, kind="edit_output")
    context_artifact = write_context_tool_output(state, call, output, kind="edit_output")
    context_read_path = model_readable_path(state, context_artifact)
    preview = visible_output(output, state)
    state.emit(
        "file.edited",
        {
            "tool_call_id": call.id,
            "tool": tool_name,
            "paths": paths,
            "ok": ok,
            "output_artifact": artifact,
            "context_artifact": context_artifact,
            "output_chars": len(output),
            "duration_ms": _duration_ms(started),
        },
    )
    return ToolResult(
        tool_name=tool_name,
        call_id=call.id,
        output=preview,
        ok=ok,
        duration_ms=_duration_ms(started),
        summary=output.strip(),
        content_preview=preview,
        artifact_path=context_artifact,
        truncated=len(preview) < len(output),
        data={
            "paths": paths,
            "output_artifact": artifact,
            "context_artifact": context_artifact,
            "output_chars": len(output),
            "duration_ms": _duration_ms(started),
        },
        metadata={"paths": paths},
        read_hints=read_hints(context_read_path, failure=not ok),
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


def _duration_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
