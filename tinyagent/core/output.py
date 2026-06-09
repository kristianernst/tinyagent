"""Run output writing for tinyagent."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tinyagent.core.contracts import Tool, tool_runtime
from tinyagent.core.diffs import join_diff_parts, new_file_patch
from tinyagent.core.events import json_safe
from tinyagent.core.path_safety import checked_relative_path, looks_like_secret_path, relative_path_is_within, resolved_relative_to
from tinyagent.core.state import Message, ModelResponse, RunState
from tinyagent.core.token_utils import estimate_tokens

ARTIFACTS_DIR = "artifacts"


def write_run_outputs(state: RunState) -> None:
    state.output_dir.mkdir(parents=True, exist_ok=True)

    (state.output_dir / "events.jsonl").write_text(
        "".join(json.dumps(event.to_json_dict(), sort_keys=True) + "\n" for event in state.events),
    )
    write_final_text(state)
    (state.output_dir / "metrics.json").write_text(json.dumps(_metrics(state), indent=2, sort_keys=True) + "\n")
    (state.output_dir / "final.diff").write_text(state.final_diff)


def write_final_text(state: RunState) -> None:
    state.output_dir.mkdir(parents=True, exist_ok=True)
    (state.output_dir / "final.md").write_text(_final_text(state))


def capture_final_diff(state: RunState) -> None:
    root = state.workspace.root
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _finalize_diff_unavailable(state, f"git unavailable: {exc}")
        return
    if result.returncode != 0:
        _finalize_diff_unavailable(state, "workspace is not a git worktree")
        return

    try:
        diff = subprocess.run(
            _final_diff_command(root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        untracked = _untracked_files(state)
    except (OSError, subprocess.TimeoutExpired) as exc:
        _finalize_diff_unavailable(state, f"git diff failed: {exc}")
        return
    untracked_diff = "".join(new_file_patch(root / path, path) for path in untracked)
    state.final_diff = join_diff_parts(diff.stdout, untracked_diff) if diff.returncode == 0 else ""
    state.emit(
        "diff.finalized",
        {
            "available": diff.returncode == 0,
            "reason": "" if diff.returncode == 0 else (diff.stderr.strip() or "git diff failed"),
            "path": "final.diff",
            "tokens": estimate_tokens(state.final_diff),
            "untracked_file_count": len(untracked),
        },
    )


def _finalize_diff_unavailable(state: RunState, reason: str) -> None:
    state.final_diff = ""
    state.emit("diff.finalized", {"available": False, "reason": reason, "path": "final.diff", "tokens": 0})


def _final_diff_command(root: Path) -> list[str]:
    if _git_has_head(root):
        return ["git", "-C", str(root), "diff", "--no-ext-diff", "HEAD", "--"]
    return ["git", "-C", str(root), "diff", "--no-ext-diff", "--"]


def _git_has_head(root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result.returncode == 0


def write_text_artifact(state: RunState, name: str, content: str, *, kind: str) -> str:
    relative_path = Path(ARTIFACTS_DIR) / checked_relative_path(name, label="Artifact name")
    artifact_path = state.output_dir / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(content)
    state.emit(
        "artifact.created",
        {
            "kind": kind,
            "path": relative_path.as_posix(),
            "bytes": len(content.encode()),
        },
    )
    return relative_path.as_posix()


def write_json_artifact(state: RunState, name: str, data: dict[str, Any], *, kind: str) -> str:
    return write_text_artifact(
        state,
        name,
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        kind=kind,
    )


def write_model_request_artifacts(
    state: RunState,
    *,
    call_index: int,
    provider: str,
    messages: list[Message],
    tools: list[Tool],
) -> tuple[str, str]:
    context_artifact = write_text_artifact(
        state,
        f"context-{call_index:04d}.md",
        _context_markdown(messages, tools),
        kind="model_context",
    )
    request_artifact = write_json_artifact(
        state,
        f"model-request-logical-{call_index:04d}.json",
        {
            "provider": provider,
            "conversation_state": (state.model_conversation_state.to_json_dict() if state.model_conversation_state is not None else None),
            "messages": [_message_dict(message) for message in messages],
            "tools": [_tool_dict(tool) for tool in tools],
        },
        kind="model_request_logical",
    )
    return context_artifact, request_artifact


def write_context_report_artifact(
    state: RunState,
    *,
    call_index: int,
    built_context,
    budget: int,
    model_capabilities=None,
) -> str:
    return write_json_artifact(
        state,
        f"context-report-{call_index:04d}.json",
        {
            "request_id": f"model-call-{call_index:04d}",
            "token_estimate": built_context.token_estimate,
            "budget": budget,
            "model_capabilities": model_capabilities.to_json_dict() if model_capabilities is not None else None,
            "context_plan": (
                built_context.context_plan.to_json_dict() if getattr(built_context, "context_plan", None) is not None else None
            ),
            "contextfs_index_path": built_context.contextfs_index_path,
            "included": [
                {
                    "id": item.id,
                    "source": item.source,
                    "tokens": item.token_estimate,
                    "priority": item.priority,
                    "stable": item.stable,
                }
                for item in built_context.included
            ],
            "excluded": [
                {
                    "id": item.item_id,
                    "reason": item.reason,
                    "tokens": item.token_estimate,
                }
                for item in built_context.excluded
            ],
        },
        kind="context_report",
    )


def write_model_http_request_artifact(
    state: RunState,
    *,
    call_index: int,
    payload: dict[str, Any],
) -> str:
    return write_json_artifact(
        state,
        f"model-request-http-{call_index:04d}.json",
        payload,
        kind="model_request_http",
    )


def write_model_response_artifact(
    state: RunState,
    *,
    call_index: int,
    response: ModelResponse,
) -> str:
    return write_json_artifact(
        state,
        f"model-response-{call_index:04d}.json",
        {
            "content": response.content,
            "finish_reason": response.finish_reason,
            "tool_calls": [_tool_call_dict(call) for call in response.tool_calls],
            "conversation_state": (response.conversation_state.to_json_dict() if response.conversation_state is not None else None),
            "raw": response.raw,
        },
        kind="model_response",
    )


def _final_text(state: RunState) -> str:
    return f"# Final output\n\n{state.final_output or 'No final output produced.'}\n"


def _metrics(state: RunState) -> dict[str, Any]:
    envelope = state.workspace_envelope
    started = next((event for event in state.events if event.type == "run.started"), None)
    return {
        "run_id": state.run_id,
        "parent_run_id": state.parent_run_id,
        "parent_event_id": state.parent_event_id,
        "branch_name": state.branch_name,
        "status": "cancelled" if state.cancelled else "failed" if state.failed else "completed",
        "terminal_status": state.terminal_status,
        "failure_reason": state.failure_reason,
        "cancel_reason": state.cancel_reason,
        "cancel_requested": state.cancelled,
        "cancel_signal_count": max(state.cancel_signal_count, state.cancel_token.signal_count),
        "cancel_escalated": state.cancel_escalated,
        "final_output_tokens": estimate_tokens(state.final_output),
        "final_output_path": "final.md",
        "task": state.task,
        "workspace_root": str(state.workspace.root),
        "original_workspace_root": str(envelope.original_root) if envelope else str(state.workspace.root),
        "output_dir": str(state.output_dir),
        "turn_count": state.turn_count,
        "model_call_count": state.model_call_count,
        "model_conversation_state": (state.model_conversation_state.to_json_dict() if state.model_conversation_state is not None else None),
        "tool_call_count": state.tool_call_count,
        "event_count": state.seq,
        "durable_event_count": len(state.events),
        "duration_seconds": state.elapsed_seconds(),
        "budgets": asdict(state.budgets),
        "final_diff_available": bool(state.final_diff),
        "context_token_estimate": state.context_token_estimate,
        "compaction_count": state.compaction_count,
        "context_checkpoint_artifact": state.context_checkpoint_artifact or None,
        "shell_policy": "best_effort",
        "shell_env": "sanitized",
        "shell_process_group": "posix",
        "shell_preflight": state.shell_preflight,
        "workspace_mode": envelope.mode if envelope else "current",
        "workspace_effective_mode": envelope.effective_mode if envelope else "current",
        "workspace_allowed_roots": [str(root) for root in envelope.allowed_roots] if envelope else [str(state.workspace.root)],
        "approval_mode": state.approval_mode,
        "session_mode": state.session_mode,
        "permission_profile": started.data.get("permission_profile", "") if started else "",
        "sandbox_mode": envelope.sandbox_mode if envelope else "none",
        "sandbox_backend": envelope.sandbox_backend if envelope else "none",
        "network_mode": envelope.network_mode if envelope else "deny",
        "sandbox_enforced": envelope.sandbox_enforced if envelope else False,
        "finalization_attempted": state.finalization_attempted,
        "pending_approval_count": len(state.pending_approvals),
        "approval_grant_count": len(state.approval_grants),
    }


def _untracked_files(state: RunState) -> list[str]:
    root = state.workspace.root
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [path for path in result.stdout.splitlines() if path and not _excluded_from_final_diff(state, path)]


def _excluded_from_final_diff(state: RunState, relative_path: str) -> bool:
    if relative_path.startswith(".tinyagent/"):
        return True
    if looks_like_secret_path(relative_path):
        return True
    output_relative = resolved_relative_to(state.output_dir, state.workspace.root)
    return output_relative is not None and relative_path_is_within(relative_path, output_relative)


def _context_markdown(messages: list[Message], tools: list[Tool]) -> str:
    sections = ["# Model Context\n"]
    sections.append("## Messages\n")
    for message in messages:
        content = message.content if isinstance(message.content, str) else json.dumps(json_safe(message.content), indent=2)
        meta = f"\n```json\n{json.dumps(json_safe(message.meta), indent=2, sort_keys=True)}\n```\n" if message.meta else ""
        sections.append(f"### {message.role}\n\n{content}\n{meta}")
    sections.append("## Visible Tools\n")
    for tool in tools:
        sections.append(f"### {tool.name}\n\n```json\n{json.dumps(_tool_dict(tool), indent=2, sort_keys=True)}\n```\n")
    return "\n".join(sections)


def _message_dict(message: Message) -> dict[str, Any]:
    data = {"role": message.role, "content": json_safe(message.content)}
    if message.meta:
        data["meta"] = json_safe(message.meta)
    return data


def _tool_dict(tool: Tool) -> dict[str, Any]:
    return {"name": tool.name, "schema": dict(tool.schema), "runtime": tool_runtime(tool).to_json_dict()}


def _tool_call_dict(call: Any) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "args": call.args}
