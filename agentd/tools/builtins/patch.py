"""Builtin OpenAI-style patch tool."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

from agentd.contextfs import read_hints, write_context_tool_output
from agentd.state import RunState, ToolCall, ToolResult
from agentd.tools.core import (
    ToolError,
    error_result,
    relative_workspace_path,
    resolve_workspace_path,
    visible_output,
    write_tool_output_artifact,
)


class ApplyPatchTool:
    name = "apply_patch"
    schema = {
        "name": "apply_patch",
        "description": "Apply a patch inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"patch": {"type": "string"}},
            "required": ["patch"],
        },
    }

    def __init__(self, *, allow_run_artifacts: bool = False) -> None:
        self.allow_run_artifacts = allow_run_artifacts

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        started = time.monotonic()
        patch = str(call.args.get("patch", ""))
        if not patch:
            return ToolResult(
                tool_name=self.name,
                call_id=call.id,
                output="patch is required",
                ok=False,
                duration_ms=_duration_ms(started),
                summary="patch is required",
                content_preview="patch is required",
                failure_kind="invalid_tool_args",
                data={"failure_kind": "invalid_tool_args"},
            )
        try:
            touched = [
                relative_workspace_path(state, resolve_workspace_path(state, path, allow_run_artifacts=self.allow_run_artifacts))
                for path in patch_paths(patch)
            ]
        except Exception as exc:
            return error_result(self.name, call, exc)
        if not touched:
            return ToolResult(
                tool_name=self.name,
                call_id=call.id,
                output="patch did not declare any file paths",
                ok=False,
                duration_ms=_duration_ms(started),
                summary="patch did not declare any file paths",
                content_preview="patch did not declare any file paths",
                failure_kind="invalid_tool_args",
                data={"failure_kind": "invalid_tool_args"},
            )

        try:
            output = apply_openai_patch(state.workspace.root, patch)
            ok = True
        except Exception as exc:
            output = str(exc)
            ok = False
        artifact = write_tool_output_artifact(state, call, "patch-output", output, kind="patch_output")
        context_artifact = write_context_tool_output(state, call, output, kind="patch_output")
        preview = visible_output(output, state)
        failure_kind = None if ok else "invalid_tool_args"
        state.emit(
            "patch.applied",
            {
                "paths": touched,
                "ok": ok,
                "output_chars": len(output),
                "output_artifact": artifact,
                "context_artifact": context_artifact,
                "duration_ms": _duration_ms(started),
                "failure_kind": failure_kind,
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=preview,
            ok=ok,
            duration_ms=_duration_ms(started),
            summary="Patch applied." if ok else output.splitlines()[0] if output else "Patch failed.",
            content_preview=preview,
            artifact_path=context_artifact,
            truncated=len(preview) < len(output),
            failure_kind=failure_kind,
            data={
                "paths": touched,
                "output_artifact": artifact,
                "context_artifact": context_artifact,
                "output_chars": len(output),
                "duration_ms": _duration_ms(started),
                "failure_kind": failure_kind,
            },
            metadata={"paths": touched},
            read_hints=read_hints(context_artifact, failure=not ok),
        )


@dataclass(frozen=True)
class PatchOperation:
    action: str
    path: str
    lines: tuple[str, ...]
    move_to: str | None = None


@dataclass(frozen=True)
class _PatchSnapshot:
    existed: bool
    data: bytes | None = None


def apply_openai_patch(root: Path, patch: str) -> str:
    operations = _parse_openai_patch(patch)
    _deny_symlink_patch_paths(root, operations)
    touched_paths = _patch_touched_paths(root, operations)
    snapshots = _snapshot_patch_paths(touched_paths)
    existing_dirs = _existing_parent_dirs(root, touched_paths)
    changed: list[str] = []
    try:
        for operation in operations:
            match operation.action:
                case "add":
                    _apply_add(root, operation)
                    changed.append(f"A {operation.path}")
                case "delete":
                    _apply_delete(root, operation)
                    changed.append(f"D {operation.path}")
                case "update":
                    _apply_update(root, operation)
                    changed.append(f"M {operation.path}" if operation.move_to is None else f"R {operation.path} -> {operation.move_to}")
                case _:
                    raise ToolError(f"Unsupported patch operation: {operation.action}")
    except Exception:
        _restore_patch_snapshot(snapshots)
        _prune_new_empty_dirs(root, touched_paths, existing_dirs)
        raise
    return "Applied patch.\n" + "\n".join(changed) + ("\n" if changed else "")


def _parse_openai_patch(patch: str) -> list[PatchOperation]:
    lines = patch.splitlines()
    if not lines or lines[0] != "*** Begin Patch":
        raise ToolError("patch must start with *** Begin Patch")
    if lines[-1] != "*** End Patch":
        raise ToolError("patch must end with *** End Patch")

    operations: list[PatchOperation] = []
    index = 1
    while index < len(lines) - 1:
        line = lines[index]
        match = re.match(r"^\*\*\* (Add|Delete|Update) File: (.+)$", line)
        if not match:
            raise ToolError(f"Expected file operation, got: {line}")
        operation = match.group(1).lower()
        path = match.group(2)
        index += 1
        move_to: str | None = None
        if operation == "update" and index < len(lines) - 1:
            move_match = re.match(r"^\*\*\* Move to: (.+)$", lines[index])
            if move_match:
                move_to = move_match.group(1)
                index += 1
        body: list[str] = []
        while index < len(lines) - 1 and not lines[index].startswith("*** "):
            body.append(lines[index])
            index += 1
        operations.append(PatchOperation(action=operation, path=path, lines=tuple(body), move_to=move_to))
    return operations


def _patch_touched_paths(root: Path, operations: list[PatchOperation]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for operation in operations:
        for path in (operation.path, operation.move_to):
            if path is None:
                continue
            resolved = _patch_path(root, path)
            if resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)
    return paths


def _snapshot_patch_paths(paths: list[Path]) -> dict[Path, _PatchSnapshot]:
    snapshots: dict[Path, _PatchSnapshot] = {}
    for path in paths:
        if not path.exists():
            snapshots[path] = _PatchSnapshot(existed=False)
            continue
        if not path.is_file():
            raise ToolError(f"Patch path is not a regular file: {path}")
        snapshots[path] = _PatchSnapshot(existed=True, data=path.read_bytes())
    return snapshots


def _restore_patch_snapshot(snapshots: dict[Path, _PatchSnapshot]) -> None:
    for path, snapshot in snapshots.items():
        if snapshot.existed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(snapshot.data or b"")
        elif path.exists():
            if path.is_file() or path.is_symlink():
                path.unlink()
            else:
                raise ToolError(f"Cannot roll back non-file patch path: {path}")


def _existing_parent_dirs(root: Path, paths: list[Path]) -> set[Path]:
    root = root.resolve()
    dirs = set(_parent_dirs(root, paths))
    return {path for path in dirs if path.exists()}


def _prune_new_empty_dirs(root: Path, paths: list[Path], existing_dirs: set[Path]) -> None:
    for path in sorted(_parent_dirs(root.resolve(), paths), key=lambda item: len(item.parts), reverse=True):
        if path in existing_dirs:
            continue
        try:
            path.rmdir()
        except OSError:
            continue


def _parent_dirs(root: Path, paths: list[Path]) -> set[Path]:
    dirs: set[Path] = set()
    for path in paths:
        parent = path.parent.resolve()
        while parent != root:
            try:
                parent.relative_to(root)
            except ValueError:
                break
            dirs.add(parent)
            parent = parent.parent
    return dirs


def _patch_path(root: Path, path: str) -> Path:
    root = root.resolve()
    candidate = Path(path).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError(f"Path is outside workspace: {path}") from exc
    return resolved


def _duration_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _raw_patch_path(root: Path, path: str) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else root / candidate


def _deny_symlink_patch_paths(root: Path, operations: list[PatchOperation]) -> None:
    for operation in operations:
        for path in (operation.path, operation.move_to):
            if path is not None and _raw_patch_path(root, path).is_symlink():
                raise ToolError(f"Cannot patch symlink path: {path}")


def _apply_add(root: Path, operation: PatchOperation) -> None:
    path = _patch_path(root, operation.path)
    if path.exists():
        raise ToolError(f"Cannot add existing file: {operation.path}")
    content = []
    for line in operation.lines:
        if not line.startswith("+"):
            raise ToolError(f"Add file lines must start with '+': {operation.path}")
        content.append(line[1:])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_join_patch_lines(content, trailing_newline=bool(content)))


def _apply_delete(root: Path, operation: PatchOperation) -> None:
    path = _patch_path(root, operation.path)
    if not path.exists():
        raise ToolError(f"Cannot delete missing file: {operation.path}")
    path.unlink()


def _apply_update(root: Path, operation: PatchOperation) -> None:
    source = _patch_path(root, operation.path)
    if not source.exists():
        raise ToolError(f"Cannot update missing file: {operation.path}")
    original_text = source.read_text(errors="replace")
    original_lines = original_text.splitlines()
    updated_lines = _apply_hunks(original_lines, operation.lines)
    target = _patch_path(root, operation.move_to or operation.path)
    if operation.move_to is not None and target.exists() and target.resolve() != source.resolve():
        raise ToolError(f"Cannot move over existing file: {operation.move_to}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_join_patch_lines(updated_lines, trailing_newline=original_text.endswith("\n")))
    if operation.move_to is not None and target.resolve() != source.resolve():
        source.unlink()


def _apply_hunks(original_lines: list[str], patch_lines: tuple[str, ...]) -> list[str]:
    if not patch_lines:
        return original_lines
    output = list(original_lines)
    cursor = 0
    for hunk in _split_hunks(patch_lines):
        old_lines = [line[1:] for line in hunk if line and line[0] in {" ", "-"}]
        new_lines = [line[1:] for line in hunk if line and line[0] in {" ", "+"}]
        position = _find_subsequence(output, old_lines, start=cursor)
        if position is None:
            raise ToolError("Patch hunk did not match file content.")
        output[position : position + len(old_lines)] = new_lines
        cursor = position + len(new_lines)
    return output


def _split_hunks(lines: tuple[str, ...]) -> list[list[str]]:
    hunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("@@"):
            if current:
                hunks.append(current)
            current = []
            continue
        if line.startswith("\\ No newline"):
            continue
        if not line or line[0] not in {" ", "-", "+"}:
            raise ToolError(f"Invalid patch hunk line: {line}")
        current.append(line)
    if current:
        hunks.append(current)
    return hunks


def _find_subsequence(lines: list[str], needle: list[str], *, start: int) -> int | None:
    if not needle:
        return start
    stop = len(lines) - len(needle) + 1
    for index in range(start, max(stop, start)):
        if lines[index : index + len(needle)] == needle:
            return index
    return None


def _join_patch_lines(lines: list[str], *, trailing_newline: bool) -> str:
    text = "\n".join(lines)
    if trailing_newline:
        return text + "\n"
    return text


def patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        match = re.match(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", line)
        if match:
            paths.append(match.group(1))
            continue
        match = re.match(r"^\*\*\* Move to: (.+)$", line)
        if match:
            paths.append(match.group(1))
    return paths
