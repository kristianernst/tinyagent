"""Safe ContextFS recovery reader."""

from __future__ import annotations

from pathlib import Path

from tinyagent.core.contextfs import allowed_context_read_paths, model_readable_path
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.tools.core import error_result, visible_output

MAX_CONTEXT_READ_BYTES = 1_000_000


class ReadContextTool:
    name = "read_context"
    schema = {
        "name": "read_context",
        "description": "Read a safe ContextFS recovery file for the current run.",
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

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        try:
            path = _resolve_context_path(state, str(call.args["path"]))
            start_line = max(int(call.args.get("start_line", 1)), 1)
            max_lines = max(int(call.args.get("max_lines", 400)), 1)
            size = path.stat().st_size
            if size > MAX_CONTEXT_READ_BYTES:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call.id,
                    output=f"context file is too large to read: {_relative_output_path(state, path)} ({size} bytes)",
                    ok=False,
                    data={"path": _relative_output_path(state, path), "bytes": size, "max_bytes": MAX_CONTEXT_READ_BYTES},
                )
            text = path.read_text(errors="replace")
        except Exception as exc:
            return error_result(self.name, call, exc)

        lines = text.splitlines()
        selected = lines[start_line - 1 : start_line - 1 + max_lines]
        numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(selected, start=start_line))
        rel = _relative_output_path(state, path)
        output = f"{rel}\n{numbered}" if numbered else f"{rel}\n"
        output_chars = len(output)
        state.emit(
            "context.read",
            {
                "path": rel,
                "start_line": start_line,
                "line_count": len(selected),
                "total_lines": len(lines),
                "bytes": len(text.encode()),
                "output_chars": output_chars,
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(output, state),
            data={
                "path": rel,
                "start_line": start_line,
                "line_count": len(selected),
                "total_lines": len(lines),
                "bytes": len(text.encode()),
                "output_chars": output_chars,
            },
            truncated=output_chars > state.budgets.max_command_output_chars_visible,
        )


def _resolve_context_path(state: RunState, value: str) -> Path:
    raw = Path(value)
    if raw.is_absolute():
        candidate = raw.resolve()
    else:
        parts = raw.parts
        if parts and parts[0] == ".tinyagent":
            candidate = (state.workspace.root / raw).resolve()
        elif parts and parts[0] in {"context", "artifacts"}:
            candidate = (state.output_dir / raw).resolve()
        else:
            candidate = (state.output_dir / "context" / raw).resolve()
    output_root = state.output_dir.resolve()
    try:
        rel = candidate.relative_to(output_root)
    except ValueError as exc:
        raise ValueError(f"Context path is outside current run output: {value}") from exc
    rel_posix = rel.as_posix()
    if rel_posix.startswith("context/"):
        if rel_posix not in allowed_context_read_paths(state):
            raise ValueError(f"Context path is not part of the current run recovery surface: {value}")
        return candidate
    if rel_posix.startswith("artifacts/context-checkpoint-") and rel_posix.endswith(".md") and _artifact_kind(state, rel_posix) == "context_checkpoint":
        return candidate
    if rel_posix.startswith("artifacts/search-output-") and _artifact_kind(state, rel_posix) == "search_captured_output":
        return candidate
    if rel_posix.startswith("artifacts/workspace-delta-") and _artifact_kind(state, rel_posix) == "workspace_delta":
        return candidate
    raise ValueError(f"Context path is not an allowed recovery file: {value}")


def _relative_output_path(state: RunState, path: Path) -> str:
    try:
        return path.resolve().relative_to(state.output_dir.resolve()).as_posix()
    except ValueError:
        return model_readable_path(state, path)


def _artifact_kind(state: RunState, relative_path: str) -> str | None:
    for event in reversed(state.events):
        if event.type == "artifact.created" and event.data.get("path") == relative_path:
            return str(event.data.get("kind") or "")
    return None
