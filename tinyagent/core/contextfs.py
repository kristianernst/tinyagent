"""Artifact-backed model-readable context filesystem."""

from __future__ import annotations

import difflib
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tinyagent.core.contextfs_render import (
    OPTIONAL_CONTEXT_FILE_RELS,
    STATIC_CONTEXT_FILE_RELS,
    TOOL_CONTEXT_DESCRIPTIONS,
    ContextIndexEntry,
    ContextRenderHelpers,
    render_context_index,
    render_diff_docs,
    render_tool_docs,
    static_context_file_specs,
)

if TYPE_CHECKING:
    from tinyagent.core.state import RunState, ToolCall, ToolStep


CONTEXT_DIR = "context"
MAX_UNTRACKED_DIFF_BYTES = 1_000_000
_STATIC_CONTEXT_FILES = frozenset(STATIC_CONTEXT_FILE_RELS)
_SECRET_FILE_NAMES = frozenset({".env", ".npmrc", ".pypirc", ".netrc"})


def contextfs_index_path(state: "RunState") -> str:
    return f"{CONTEXT_DIR}/INDEX.md"


def model_readable_path(state: "RunState", context_relative: str | Path) -> str:
    absolute = (state.output_dir / context_relative).resolve()
    try:
        return absolute.relative_to(state.workspace.root.resolve()).as_posix()
    except ValueError:
        return absolute.as_posix()


def context_display_ref(context_relative: str | Path) -> str:
    rel = Path(context_relative).as_posix()
    if rel.startswith(("context/", "artifacts/")):
        return rel
    return f"context/{rel}"


def resolve_context_path(state: "RunState", value: str) -> Path:
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
            candidate = (state.output_dir / CONTEXT_DIR / raw).resolve()
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
    if (
        rel_posix.startswith("artifacts/context-checkpoint-")
        and rel_posix.endswith(".md")
        and artifact_kind(state, rel_posix) == "context_checkpoint"
    ):
        return candidate
    if (
        rel_posix.startswith("artifacts/context-search-")
        and rel_posix.endswith(".txt")
        and artifact_kind(state, rel_posix) == "context_search_output"
    ):
        return candidate
    if (
        rel_posix.startswith("artifacts/context-read-")
        and rel_posix.endswith(".txt")
        and artifact_kind(state, rel_posix) == "context_read_output"
    ):
        return candidate
    if rel_posix.startswith("artifacts/workspace-delta-") and artifact_kind(state, rel_posix) == "workspace_delta":
        return candidate
    raise ValueError(f"Context path is not an allowed recovery file: {value}")


def relative_output_path(state: "RunState", path: Path) -> str:
    try:
        return path.resolve().relative_to(state.output_dir.resolve()).as_posix()
    except ValueError:
        return model_readable_path(state, path)


def artifact_kind(state: "RunState", relative_path: str) -> str | None:
    for event in reversed(state.events):
        if event.type == "artifact.created" and event.data.get("path") == relative_path:
            return str(event.data.get("kind") or "")
    return None


def write_context_tool_output(state: "RunState", call: "ToolCall", output: str, *, kind: str) -> str:
    sequence = len(state.tool_steps) + 1
    if call.name == "shell":
        tool_dir = "shell"
    elif call.name in {"apply_patch", "str_replace_edit", "write_file"}:
        tool_dir = "patch"
    else:
        tool_dir = safe_artifact_name(call.name)
    path = Path(CONTEXT_DIR) / tool_dir / f"{sequence:04d}-{safe_artifact_name(call.id)}.txt"
    absolute = state.output_dir / path
    absolute.parent.mkdir(parents=True, exist_ok=True)
    absolute.write_text(output)
    state.emit(
        "contextfs.artifact.written",
        {
            "path": path.as_posix(),
            "kind": kind,
            "tool_call_id": call.id,
            "tool": call.name,
            "bytes": len(output.encode()),
        },
    )
    return path.as_posix()


def read_hints(path: str, *, failure: bool = False) -> list[str]:
    quoted = shlex.quote(path)
    hints = [f"tail -120 {quoted}"]
    if failure:
        hints.append(f"rg \"FAILED|ERROR|Traceback|AssertionError\" {quoted}")
    return hints


def allowed_context_read_paths(state: "RunState") -> set[str]:
    paths = set(_STATIC_CONTEXT_FILES)
    for optional in OPTIONAL_CONTEXT_FILE_RELS:
        if (state.output_dir / optional).exists():
            paths.add(optional)
    for tool_name in TOOL_CONTEXT_DESCRIPTIONS:
        paths.add(f"context/tools/{safe_artifact_name(tool_name)}.md")
    for event in state.events:
        if event.type == "contextfs.artifact.written":
            path = event.data.get("path")
            if isinstance(path, str) and path.startswith("context/"):
                paths.add(path)
    for step in state.tool_steps:
        for artifact in _tool_artifact_candidates(step):
            if isinstance(artifact, str) and artifact.startswith("context/"):
                paths.add(artifact)
    for path in _diff_doc_paths(state):
        paths.add(path)
    return paths


def refresh_contextfs(state: "RunState") -> str:
    context_dir = state.output_dir / CONTEXT_DIR
    context_dir.mkdir(parents=True, exist_ok=True)
    helpers = _context_render_helpers(state)
    specs = static_context_file_specs(helpers)
    entries = [spec.index_entry() for spec in specs if spec.include_in_index]
    entries.extend(
        [
            ContextIndexEntry(
                path="context/tools/INDEX.md",
                section="Recovery",
                description="recovery notes for available tool output files.",
            ),
            ContextIndexEntry(
                path="context/diffs/INDEX.md",
                section="Recovery",
                description="mutation diff artifacts copied into ContextFS.",
            ),
        ]
    )
    for optional in OPTIONAL_CONTEXT_FILE_RELS:
        if (state.output_dir / optional).exists():
            entries.append(
                ContextIndexEntry(
                    path=optional,
                    section="Recovery",
                    description="run-scoped working todo state.",
                )
            )
    for spec in specs:
        _write_text(state, spec.rel, spec.render(state))
    for rendered in (*render_tool_docs(state, helpers), *render_diff_docs(state, helpers)):
        _write_text(state, rendered.rel, rendered.content)
    index = render_context_index(state, entries, helpers)
    _write_text(state, "context/INDEX.md", index)
    return contextfs_index_path(state)


def _write_text(state: "RunState", relative: str, content: str) -> None:
    rel = Path(relative)
    if not rel.parts or rel.parts[0] != CONTEXT_DIR:
        rel = Path(CONTEXT_DIR) / rel
    path = state.output_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _context_render_helpers(state: "RunState") -> ContextRenderHelpers:
    return ContextRenderHelpers(
        context_ref=context_display_ref,
        safe_recovery_artifact_ref=lambda artifact: _safe_recovery_artifact_ref(state, artifact),
        primary_tool_artifact=_primary_tool_artifact,
        safe_transcript_refs=lambda refs: _safe_transcript_refs(state, refs),
        sanitize_value=lambda value: _sanitize_context_value(state, value),
        sanitize_data=lambda value: _sanitize_context_data(state, value),
        repo_status_text=lambda: _repo_status_text(state),
        repo_diff_text=lambda: _repo_diff_text(state),
        raw_history_text=lambda: _raw_history_text(state),
        safe_artifact_name=safe_artifact_name,
        diff_artifact_targets=lambda: _diff_artifact_targets(state),
    )


def _repo_status_text(state: "RunState") -> str:
    status = _git(state, ["status", "--short"])
    paths = _tracked_diff_paths(state)
    diff_stat = _tracked_diff_stat(state, paths)
    lines = ["# Current Status", ""]
    if status is None:
        lines.extend(["Git status unavailable.", ""])
    else:
        filtered_status = _filter_hidden_status(state, status)
        lines.extend(["## git status --short", "", "```text", filtered_status.strip() or "(clean)", "```", ""])
    if diff_stat is not None:
        lines.extend(["## git diff --stat HEAD --", "", "```text", diff_stat.strip() or "(no diff)", "```", ""])
    return "\n".join(lines)


def _repo_diff_text(state: "RunState") -> str:
    paths = _tracked_diff_paths(state)
    diff = ""
    if paths:
        diff_args = ["diff", "--no-ext-diff", "HEAD", "--", *paths] if _git_has_head(state) else ["diff", "--no-ext-diff", "--", *paths]
        diff = _git(state, diff_args) or ""
    untracked = _untracked_diff_text(state)
    return _join_nonempty(diff, untracked)


def _raw_history_text(state: "RunState") -> str:
    events_path = state.output_dir / "events.jsonl"
    if events_path.exists():
        lines = []
        for line in events_path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            safe_event = {
                "seq": event.get("seq"),
                "type": event.get("type"),
                "time": event.get("time"),
                "turn_id": event.get("turn_id"),
                "item_id": event.get("item_id"),
                "visibility": event.get("visibility"),
                "artifact_refs": [
                    artifact
                    for artifact in event.get("artifact_refs", [])
                    if _safe_recovery_artifact_ref(state, artifact)
                ],
                "data": _safe_event_data(state, str(event.get("type") or ""), event.get("data") if isinstance(event.get("data"), dict) else {}),
            }
            lines.append(json.dumps(safe_event, sort_keys=True))
        return "\n".join(lines) + ("\n" if lines else "")
    return ""


def _safe_transcript_refs(state: "RunState", refs: tuple[str, ...]) -> str:
    if not refs:
        return "(none)"
    safe = [_safe_recovery_artifact_ref(state, ref) for ref in refs]
    rendered = [ref for ref in safe if ref]
    if not rendered:
        return "(internal artifacts not exposed through ContextFS)"
    return ", ".join(rendered)


def _safe_recovery_artifact_ref(state: "RunState", artifact: object) -> str | None:
    if not isinstance(artifact, str):
        return None
    if artifact.startswith("context/"):
        return artifact
    if artifact.startswith("artifacts/context-checkpoint-") and artifact.endswith(".md") and _artifact_kind(state, artifact) == "context_checkpoint":
        return artifact
    if artifact.startswith("artifacts/context-search-") and artifact.endswith(".txt") and _artifact_kind(state, artifact) == "context_search_output":
        return artifact
    if artifact.startswith("artifacts/context-read-") and artifact.endswith(".txt") and _artifact_kind(state, artifact) == "context_read_output":
        return artifact
    if artifact.startswith("artifacts/workspace-delta-") and _artifact_kind(state, artifact) == "workspace_delta":
        return artifact
    return None


def _tool_artifact_candidates(step: "ToolStep") -> tuple[object, ...]:
    return (
        step.result.artifact_path,
        step.result.data.get("context_artifact"),
        step.result.data.get("output_artifact"),
        step.result.data.get("captured_output_artifact"),
    )


def _primary_tool_artifact(step: "ToolStep") -> object:
    for artifact in _tool_artifact_candidates(step):
        if artifact:
            return artifact
    return None


def _diff_doc_paths(state: "RunState") -> list[str]:
    return [target for _artifact, target in _diff_artifact_targets(state)]


def _diff_artifact_targets(state: "RunState") -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for event in state.events:
        if event.type != "diff.snapshot":
            continue
        artifact = _safe_recovery_artifact_ref(state, event.data.get("path"))
        if not artifact or artifact in seen:
            continue
        seen.add(artifact)
        target_name = f"{len(seen):04d}-{safe_artifact_name(Path(artifact).name)}"
        output.append((artifact, (Path(CONTEXT_DIR) / "diffs" / target_name).as_posix()))
    return output


def _artifact_kind(state: "RunState", artifact: str) -> str | None:
    for event in reversed(state.events):
        if event.type == "artifact.created" and event.data.get("path") == artifact:
            return str(event.data.get("kind") or "")
    return None


def _untracked_diff_text(state: "RunState") -> str:
    paths = _git(state, ["ls-files", "--others", "--exclude-standard"])
    if not paths:
        return ""
    parts: list[str] = []
    for path in [line for line in paths.splitlines() if line.strip()]:
        if _is_hidden_recovery_path(state, path):
            continue
        absolute = state.workspace.root / path
        if absolute.is_symlink() or not absolute.is_file():
            continue
        try:
            file_size = absolute.stat().st_size
        except OSError:
            continue
        header = f"diff --git a/{path} b/{path}\nnew file mode 100644\nindex 0000000..0000000\n"
        if file_size > MAX_UNTRACKED_DIFF_BYTES:
            parts.append(f"{header}Binary files /dev/null and b/{path} differ\n")
            continue
        try:
            raw = absolute.read_bytes()
        except OSError:
            continue
        if b"\0" in raw:
            parts.append(f"{header}Binary files /dev/null and b/{path} differ\n")
            continue
        text = raw.decode(errors="replace")
        body = "\n".join(difflib.unified_diff([], text.splitlines(), fromfile="/dev/null", tofile=f"b/{path}", lineterm=""))
        parts.extend(
            [
                header.rstrip(),
                body,
                "",
            ]
        )
    return "\n".join(parts)


def _join_nonempty(*parts: str) -> str:
    return "\n".join(part.rstrip() for part in parts if part and part.strip()) + ("\n" if any(part and part.strip() for part in parts) else "")


def _filter_hidden_status(state: "RunState", status: str) -> str:
    return "\n".join(line for line in status.splitlines() if not _is_hidden_recovery_path(state, line[3:].strip() if len(line) > 3 else line.strip()))


def _tracked_diff_paths(state: "RunState") -> list[str]:
    args = ["diff", "--name-only", "HEAD", "--"] if _git_has_head(state) else ["diff", "--name-only", "--"]
    output = _git(state, args)
    if not output:
        return []
    return [path for path in output.splitlines() if path and not _is_hidden_recovery_path(state, path)]


def _tracked_diff_stat(state: "RunState", paths: list[str]) -> str | None:
    if not paths:
        return ""
    args = ["diff", "--stat", "HEAD", "--", *paths] if _git_has_head(state) else ["diff", "--stat", "--", *paths]
    return _git(state, args)


def _is_hidden_recovery_path(state: "RunState", path: str) -> bool:
    normalized = path.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized == ".tinyagent" or normalized.startswith(".tinyagent/"):
        return True
    if _is_output_dir_path(state, normalized):
        return True
    for part in Path(normalized).parts:
        if part == ".ssh":
            return True
        if part in _SECRET_FILE_NAMES or part.startswith(".env."):
            return True
    return False


def _is_output_dir_path(state: "RunState", path: str) -> bool:
    try:
        output_relative = state.output_dir.resolve().relative_to(state.workspace.root.resolve()).as_posix()
    except ValueError:
        return False
    if output_relative in {"", "."}:
        return True
    return path == output_relative or path.startswith(f"{output_relative}/")


def _safe_event_data(state: "RunState", event_type: str, data: dict) -> dict[str, object]:
    match event_type:
        case "run.started":
            return {
                "task": data.get("task"),
                "workspace_mode": data.get("workspace_mode"),
                "approval_mode": data.get("approval_mode"),
                "sandbox_mode": data.get("sandbox_mode"),
                "sandbox_backend": data.get("sandbox_backend"),
                "sandbox_enforced": data.get("sandbox_enforced"),
            }
        case "run.completed" | "run.failed" | "run.cancelled" | "run.timed_out":
            return {"status": data.get("status"), "reason": data.get("reason")}
        case "contextfs.index.updated":
            return {"path": data.get("path"), "phase": data.get("phase")}
        case "context.built":
            return {
                "token_estimate": data.get("token_estimate"),
                "checkpoint_artifact": _safe_recovery_artifact_ref(state, data.get("checkpoint_artifact")),
            }
        case "file.read" | "files.listed":
            path = str(data.get("path") or "")
            return {"path": path if not _is_hidden_recovery_path(state, path) else "(hidden)", "line_count": data.get("line_count")}
        case "search.completed":
            return {
                "query": data.get("query"),
                "match_count": data.get("match_count"),
                "truncated": data.get("truncated"),
                "timed_out": data.get("timed_out"),
                "captured_output_artifact": _safe_recovery_artifact_ref(state, data.get("captured_output_artifact")),
            }
        case "workspace.mutation.detected" | "workspace.delta.completed":
            return {"mutated": data.get("mutated"), "paths": _safe_paths(state, data.get("paths"))}
        case "file.changed":
            path = str(data.get("path") or "")
            return {"path": path if not _is_hidden_recovery_path(state, path) else "(hidden)", "tool": data.get("tool")}
        case "diff.snapshot":
            return {"path": _safe_recovery_artifact_ref(state, data.get("path")), "paths": _safe_paths(state, data.get("paths"))}
        case "observation.recorded":
            subject = str(data.get("subject") or "")
            return {"kind": data.get("kind"), "subject": subject if not _is_hidden_recovery_path(state, subject) else "(hidden)"}
        case "policy.evaluated":
            return {"tool": data.get("tool"), "kind": data.get("kind"), "permission": data.get("permission")}
        case "tool.execution.started" | "tool.execution.completed" | "tool.execution.failed" | "tool.execution.blocked":
            return {"tool": data.get("tool"), "failure_kind": data.get("failure_kind")}
        case "command.completed" | "command.failed" | "command.cancelled" | "command.timeout":
            return {"returncode": data.get("returncode"), "ok": data.get("ok"), "timeout": data.get("timeout")}
        case "patch.applied" | "file.edited":
            return {"paths": _safe_paths(state, data.get("paths")), "ok": data.get("ok")}
        case "artifact.created":
            path = _safe_recovery_artifact_ref(state, data.get("path"))
            return {"kind": data.get("kind"), "path": path, "bytes": data.get("bytes")} if path else {"kind": data.get("kind"), "path": "(internal)", "bytes": data.get("bytes")}
        case _:
            return {}


def _safe_paths(state: "RunState", value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    paths: list[str] = []
    for item in value:
        path = str(item)
        paths.append(path if not _is_hidden_recovery_path(state, path) else "(hidden)")
    return paths


def _sanitize_context_data(state: "RunState", value: Any) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in {"cmd", "command", "args", "raw", "payload", "request", "response", "output", "output_preview"}:
                output[key_text] = "(redacted)"
            else:
                output[key_text] = _sanitize_context_data(state, item)
        return output
    if isinstance(value, list):
        return [_sanitize_context_data(state, item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_context_data(state, item) for item in value]
    if isinstance(value, str):
        return _sanitize_context_value(state, value)
    return value


def _sanitize_context_value(state: "RunState", value: str) -> str:
    output = str(value)
    output = re.sub(r"artifacts/(model-(?:request|response)[A-Za-z0-9_.-]*|context-report-[A-Za-z0-9_.-]*|context-[0-9][A-Za-z0-9_.-]*)", "(internal artifact)", output)
    output = re.sub(r"(?i)(token|api[_-]?key|password|secret)=([^\s&]+)", r"\1=(redacted)", output)
    for secret_name in _SECRET_FILE_NAMES:
        output = output.replace(secret_name, "(hidden)")
    output = re.sub(r"\.env\.[A-Za-z0-9_.-]+", "(hidden)", output)
    root_text = state.workspace.root.as_posix()
    output_text = state.output_dir.as_posix()
    output = output.replace(output_text, "(run output)")
    output = output.replace(root_text, "(workspace)")
    return output


def _git(state: "RunState", args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(state.workspace.root), *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _git_has_head(state: "RunState") -> bool:
    return _git(state, ["rev-parse", "--verify", "HEAD"]) is not None


def safe_artifact_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "call")
