"""Typed observations extracted from raw tool results."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from tinyagent.core.context.checkpoint import is_test_command_text
from tinyagent.core.state import RunState, ToolCall, ToolResult


@dataclass(frozen=True)
class Observation:
    kind: str
    subject: str
    summary: str
    confidence: float = 1.0
    refs: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_observations(call: ToolCall, result: ToolResult, state: RunState) -> list[Observation]:
    del state
    if call.name in {"apply_patch", "str_replace_edit", "write_file"}:
        return _patch_observations(call, result)
    if call.name == "shell":
        return _shell_observations(call, result)
    if call.name == "read_file":
        return _read_file_observations(call, result)
    if call.name == "read_context":
        return _read_context_observations(call, result)
    if call.name == "search_repo":
        return _search_repo_observations(call, result)
    if result.data.get("blocked") or (result.failure_kind or result.data.get("failure_kind")) in {"policy_denied", "sandbox_blocked"}:
        return [_block_observation(call, result)]
    if not result.ok:
        return [_command_failure_observation(call, result)]
    return []


def _shell_observations(call: ToolCall, result: ToolResult) -> list[Observation]:
    cmd = str(call.args.get("cmd") or result.data.get("cmd") or "")
    refs = _result_refs(result)
    observations: list[Observation] = []
    if _is_policy_block(result):
        observations.append(_block_observation(call, result))
        return observations
    if _is_diff_command(cmd) and result.ok:
        observations.append(
            Observation(
                kind="diff_seen",
                subject=cmd,
                summary=f"Diff/status evidence inspected with `{cmd}`.",
                refs=refs,
                data={"cmd": cmd},
            )
        )
    if _is_search_command(cmd) and result.ok:
        observations.append(
            Observation(
                kind="search_result",
                subject=cmd,
                summary=f"Search completed with `{cmd}`.",
                refs=refs,
                data={"cmd": cmd},
            )
        )
    if is_test_command_text(cmd) or _is_verification_command(cmd):
        observations.append(
            Observation(
                kind="verification" if result.ok else "test_failure",
                subject=cmd,
                summary=f"Verification {'passed' if result.ok else 'failed'} for `{cmd}`.",
                refs=refs,
                data={"cmd": cmd, "exit_code": result.exit_code},
            )
        )
    elif not result.ok:
        observations.append(_command_failure_observation(call, result, cmd=cmd))
    return observations


def _patch_observations(call: ToolCall, result: ToolResult) -> list[Observation]:
    refs = _result_refs(result)
    paths = result.metadata.get("paths") or result.data.get("paths") or []
    observations: list[Observation] = []
    if _is_policy_block(result):
        return [_block_observation(call, result)]
    if not result.ok:
        observations.append(
            Observation(
                kind="patch_failed",
                subject=call.id,
                summary=result.summary or _first_line(result.output) or "Patch failed.",
                refs=refs,
                data={"failure_kind": result.failure_kind or result.data.get("failure_kind")},
            )
        )
        return observations
    observations.append(
        Observation(
            kind="patch_applied",
            subject=", ".join(str(path) for path in paths) if paths else call.id,
            summary=result.summary or "Patch applied.",
            refs=refs,
            data={"paths": [str(path) for path in paths]},
        )
    )
    for path in paths:
        observations.append(
            Observation(
                kind="file_changed",
                subject=str(path),
                summary=f"{path} changed by {call.name}.",
                refs=refs,
                data={"path": str(path), "tool_call_id": call.id},
            )
        )
    return observations


def _read_file_observations(call: ToolCall, result: ToolResult) -> list[Observation]:
    if _is_policy_block(result):
        return [_block_observation(call, result)]
    if not result.ok:
        return [_command_failure_observation(call, result)]
    path = str(result.data.get("path") or call.args.get("path") or "")
    line_count = result.data.get("line_count")
    summary = f"Read {line_count} line(s) from {path}." if line_count is not None else f"Read {path}."
    return [
        Observation(
            kind="file_read",
            subject=path,
            summary=summary,
            refs=_result_refs(result),
            data={
                "path": path,
                "start_line": result.data.get("start_line"),
                "line_count": result.data.get("line_count"),
                "total_lines": result.data.get("total_lines"),
                "tool_call_id": call.id,
            },
        )
    ]


def _read_context_observations(call: ToolCall, result: ToolResult) -> list[Observation]:
    if _is_policy_block(result):
        return [_block_observation(call, result)]
    if not result.ok:
        return [_command_failure_observation(call, result)]
    path = str(result.data.get("path") or call.args.get("path") or "")
    return [
        Observation(
            kind="context_read",
            subject=path,
            summary=f"Read ContextFS recovery file {path}.",
            refs=_result_refs(result),
            data={"path": path, "tool_call_id": call.id},
        )
    ]


def _search_repo_observations(call: ToolCall, result: ToolResult) -> list[Observation]:
    if _is_policy_block(result):
        return [_block_observation(call, result)]
    if not result.ok:
        return [_command_failure_observation(call, result)]
    query = str(result.data.get("query") or call.args.get("query") or "")
    path = str(result.data.get("path") or call.args.get("path") or ".")
    match_count = result.data.get("match_count")
    summary = f"Search for {query!r} in {path} returned {match_count} match(es)."
    return [
        Observation(
            kind="search_result",
            subject=query,
            summary=summary,
            refs=_result_refs(result),
            data={
                "query": query,
                "path": path,
                "match_count": match_count,
                "truncated": result.data.get("truncated"),
                "tool_call_id": call.id,
            },
        )
    ]


def _block_observation(call: ToolCall, result: ToolResult) -> Observation:
    failure_kind = result.failure_kind or result.data.get("failure_kind")
    kind = "sandbox_block" if failure_kind == "sandbox_blocked" or result.data.get("source") == "sandbox" else "policy_block"
    permission = str(result.data.get("permission") or result.data.get("matched_rule") or result.failure_kind or "policy")
    return Observation(
        kind=kind,
        subject=call.name,
        summary=result.summary or _first_line(result.output) or "Tool call blocked.",
        refs=_result_refs(result),
        data={
            "permission": permission,
            "tool_call_id": call.id,
            "failure_kind": failure_kind,
            "capability": result.data.get("capability") or permission,
            "source": result.data.get("source") or "policy",
            "recoverability": result.data.get("recoverability") or "choose_alternative",
        },
    )


def _command_failure_observation(call: ToolCall, result: ToolResult, *, cmd: str | None = None) -> Observation:
    subject = cmd or str(call.args.get("cmd") or call.name)
    return Observation(
        kind="command_failed",
        subject=subject,
        summary=result.summary or _first_line(result.output) or "Command failed.",
        refs=_result_refs(result),
        data={
            "cmd": subject,
            "exit_code": result.exit_code,
            "failure_kind": result.failure_kind or result.data.get("failure_kind"),
            "capability": result.data.get("capability"),
            "source": result.data.get("source"),
            "recoverability": result.data.get("recoverability"),
        },
    )


def _result_refs(result: ToolResult) -> tuple[str, ...]:
    refs: list[str] = []
    for value in (result.artifact_path, result.data.get("context_artifact"), result.data.get("output_artifact")):
        if isinstance(value, str) and value and value not in refs:
            refs.append(value)
    return tuple(refs)


def _is_policy_block(result: ToolResult) -> bool:
    return bool(result.data.get("blocked")) or (result.failure_kind or result.data.get("failure_kind")) in {
        "policy_denied",
        "sandbox_blocked",
    }


def _is_diff_command(command: str) -> bool:
    text = command.lower()
    return any(pattern in text for pattern in ("git diff", "git show", "git status"))


def _is_search_command(command: str) -> bool:
    return re.search(r"(^|[;&|]\s*)rg\b", command) is not None


def _is_verification_command(command: str) -> bool:
    text = command.lower()
    return any(token in text for token in ("ruff", "mypy", "-m unittest", "-m pytest"))


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0][:240] if text.strip() else ""
