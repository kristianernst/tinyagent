"""Artifact-backed model-readable context filesystem."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from agentd.context.builder import render_environment_context

if False:  # pragma: no cover
    from agentd.state import RunState, ToolCall


CONTEXT_DIR = "context"


def contextfs_index_path(state: "RunState") -> str:
    return f"{CONTEXT_DIR}/INDEX.md"


def model_readable_path(state: "RunState", context_relative: str | Path) -> str:
    absolute = (state.output_dir / context_relative).resolve()
    try:
        return absolute.relative_to(state.workspace.root.resolve()).as_posix()
    except ValueError:
        return absolute.as_posix()


def write_context_tool_output(state: "RunState", call: "ToolCall", output: str, *, kind: str) -> str:
    sequence = len(state.tool_steps) + 1
    tool_dir = "shell" if call.name == "shell" else "patch" if call.name == "apply_patch" else safe_artifact_name(call.name)
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


def refresh_contextfs(state: "RunState") -> str:
    context_dir = state.output_dir / CONTEXT_DIR
    context_dir.mkdir(parents=True, exist_ok=True)
    _write_text(state, "task.md", _task_text(state))
    _write_text(state, "environment.md", render_environment_context(state))
    _write_text(state, "current_diff.md", _repo_state_text(state))
    _write_text(state, "last_failure.md", _last_failure_text(state))
    _write_text(state, "history/compacted.md", _compacted_history_text(state))
    _write_text(state, "history/raw.jsonl", _raw_history_text(state))
    index = _index_text(state)
    _write_text(state, "INDEX.md", index)
    return contextfs_index_path(state)


def _write_text(state: "RunState", relative: str, content: str) -> None:
    path = state.output_dir / CONTEXT_DIR / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _task_text(state: "RunState") -> str:
    return "\n".join(
        [
            "# Task",
            "",
            state.task,
            "",
            f"run_id: {state.run_id}",
            f"status: {state.status}",
            f"turn_count: {state.turn_count}",
            f"tool_call_count: {state.tool_call_count}",
            "",
        ]
    )


def _repo_state_text(state: "RunState") -> str:
    status = _git(state, ["status", "--short"])
    diff_stat = _git(state, ["diff", "--stat", "HEAD", "--"])
    lines = ["# Current Repo State", ""]
    if status is None:
        lines.extend(["Git status unavailable.", ""])
    else:
        lines.extend(["## git status --short", "", "```text", status.strip() or "(clean)", "```", ""])
    if diff_stat is not None:
        lines.extend(["## git diff --stat HEAD --", "", "```text", diff_stat.strip() or "(no diff)", "```", ""])
    return "\n".join(lines)


def _last_failure_text(state: "RunState") -> str:
    for step in reversed(state.tool_steps):
        if step.result.ok:
            continue
        artifact = step.result.artifact_path or step.result.data.get("context_artifact") or step.result.data.get("output_artifact")
        readable_artifact = model_readable_path(state, artifact) if artifact else "(none)"
        return "\n".join(
            [
                "# Last Failure",
                "",
                f"tool: {step.call.name}",
                f"call_id: {step.call.id}",
                f"failure_kind: {step.result.failure_kind or step.result.data.get('failure_kind') or 'unknown'}",
                f"artifact: {readable_artifact}",
                "",
                "## Preview",
                "",
                "```text",
                step.result.content_preview or step.result.output,
                "```",
                "",
            ]
        )
    return "# Last Failure\n\nNo failing tool result yet.\n"


def _index_text(state: "RunState") -> str:
    task_path = model_readable_path(state, "context/task.md")
    diff_path = model_readable_path(state, "context/current_diff.md")
    environment_path = model_readable_path(state, "context/environment.md")
    failure_path = model_readable_path(state, "context/last_failure.md")
    compacted_path = model_readable_path(state, "context/history/compacted.md")
    raw_history_path = model_readable_path(state, "context/history/raw.jsonl")
    lines = [
        "# tinyagent ContextFS",
        "",
        "Read only what is needed. Large outputs are stored here to keep prompt context bounded.",
        "",
        "## Task",
        f"- {task_path}: original task and current run state.",
        "",
        "## Current Repo State",
        f"- {diff_path}: latest git status and diff stat.",
        f"- {environment_path}: cwd, shell, workspace, approvals, and sandbox metadata.",
        "",
        "## Recent Failures",
        f"- {failure_path}: latest failing tool result, if any.",
        "",
        "## Tool Outputs",
    ]
    if not state.tool_steps:
        lines.append("- No tool outputs yet.")
    else:
        for step in state.tool_steps:
            artifact = step.result.artifact_path or step.result.data.get("context_artifact") or step.result.data.get("output_artifact")
            ok = "ok" if step.result.ok else "failed"
            if artifact:
                readable = model_readable_path(state, artifact)
                lines.append(f"- {readable}: {step.call.name} `{step.call.id}` {ok}. Artifact id: `{artifact}`.")
                for hint in step.result.read_hints:
                    lines.append(f"  Suggested read: `{hint}`")
            else:
                lines.append(f"- {step.call.name} `{step.call.id}` {ok}: no artifact.")
    lines.extend(
        [
            "",
            "## History",
            f"- {compacted_path}: latest compacted checkpoint summary, if any.",
            f"- {raw_history_path}: durable event log snapshot for this run.",
            "",
        ]
    )
    return "\n".join(lines)


def _compacted_history_text(state: "RunState") -> str:
    if state.context_checkpoint.strip():
        artifact = f"\n\nCheckpoint artifact: {state.context_checkpoint_artifact}" if state.context_checkpoint_artifact else ""
        return f"# Compacted History\n\n{state.context_checkpoint.strip()}{artifact}\n"
    return "# Compacted History\n\nNo compaction checkpoint yet.\n"


def _raw_history_text(state: "RunState") -> str:
    events_path = state.output_dir / "events.jsonl"
    if events_path.exists():
        return events_path.read_text()
    return ""


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


def safe_artifact_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "call")
