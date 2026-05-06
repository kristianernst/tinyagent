"""Structured summaries for recorded tinyagent runs."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tinyagent.core.events import Event
from tinyagent.runtime.replay import load_run_events


@dataclass(frozen=True)
class ModelCallRecord:
    provider: str = ""
    turn: int = 0
    streamed: bool = False
    tool_call_count: int = 0
    finish_reason: str | None = None
    request_artifact: str = ""
    response_artifact: str = ""
    failed: bool = False
    cancelled: bool = False
    failure_reason: str = ""


@dataclass(frozen=True)
class ToolCallRecord:
    tool: str = ""
    tool_call_id: str = ""
    ok: bool | None = None
    blocked: bool = False
    cancelled: bool = False
    output_chars: int = 0
    output_artifact: str = ""


@dataclass(frozen=True)
class CommandRecord:
    cmd: str = ""
    ok: bool | None = None
    timeout: bool = False
    cancelled: bool = False
    returncode: int | None = None
    output_chars: int = 0
    output_artifact: str = ""


@dataclass(frozen=True)
class RunRecord:
    run_path: str
    run_id: str = ""
    parent_run_id: str | None = None
    parent_event_id: str | None = None
    task: str = ""
    status: str = "unknown"
    failure_reason: str = ""
    final_output_path: str = "final.md"
    final_output_chars: int = 0
    final_diff_path: str = "final.diff"
    final_diff_chars: int = 0
    final_diff_available: bool = False
    duration_seconds: float = 0.0
    turn_count: int = 0
    model_call_count: int = 0
    tool_call_count: int = 0
    event_count: int = 0
    artifact_count: int = 0
    command_count: int = 0
    patch_count: int = 0
    model_calls: list[ModelCallRecord] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    commands: list[CommandRecord] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_run_record(run_path: Path) -> RunRecord:
    root = run_path if run_path.name != "events.jsonl" else run_path.parent
    events = load_run_events(run_path)
    metrics = _read_json(root / "metrics.json")
    final_diff = _read_text(root / "final.diff")
    started = _first_event(events, "run.started")
    task = str(started.data.get("task") or "") if started else ""
    run_id = str(metrics.get("run_id") or (events[0].run_id if events else ""))
    status = str(metrics.get("status") or _status_from_events(events))
    failure_reason = str(metrics.get("failure_reason") or _failure_from_events(events) or "")

    model_calls = _model_calls(events)
    tool_calls = _tool_calls(events)
    commands = _commands(events)
    diff_event = _last_event(events, "diff.finalized")
    final_diff_chars = int(diff_event.data.get("chars", len(final_diff))) if diff_event else len(final_diff)
    final_diff_available = bool(diff_event.data.get("available")) if diff_event else bool(final_diff)

    return RunRecord(
        run_path=str(root),
        run_id=run_id,
        parent_run_id=metrics.get("parent_run_id") or (started.data.get("parent_run_id") if started else None),
        parent_event_id=metrics.get("parent_event_id") or (started.data.get("parent_event_id") if started else None),
        task=str(metrics.get("task") or task),
        status=status,
        failure_reason=failure_reason,
        final_output_path=str(metrics.get("final_output_path") or "final.md"),
        final_output_chars=int(metrics.get("final_output_chars") or 0),
        final_diff_chars=final_diff_chars,
        final_diff_available=final_diff_available,
        duration_seconds=float(metrics.get("duration_seconds") or 0.0),
        turn_count=int(metrics.get("turn_count") or 0),
        model_call_count=int(metrics.get("model_call_count") or len(model_calls)),
        tool_call_count=int(metrics.get("tool_call_count") or len(tool_calls)),
        event_count=int(metrics.get("event_count") or (events[-1].seq if events else 0)),
        artifact_count=sum(1 for event in events if event.type == "artifact.created"),
        command_count=len(commands),
        patch_count=sum(1 for event in events if event.type in {"patch.applied", "file.edited"}),
        model_calls=model_calls,
        tool_calls=tool_calls,
        commands=commands,
    )


def render_run_inspection(record: RunRecord) -> str:
    lines = [
        "# Tinyagent Run Inspect",
        "",
        f"run_id: {record.run_id}",
        f"parent_run_id: {record.parent_run_id or ''}",
        f"parent_event_id: {record.parent_event_id or ''}",
        f"status: {record.status}",
        f"task: {record.task}",
        f"run_path: {record.run_path}",
        f"duration_seconds: {record.duration_seconds:.3f}",
        f"turns: {record.turn_count}",
        f"model_calls: {record.model_call_count}",
        f"tool_calls: {record.tool_call_count}",
        f"commands: {record.command_count}",
        f"patches: {record.patch_count}",
        f"events: {record.event_count}",
        f"artifacts: {record.artifact_count}",
        f"final_output: {record.final_output_path} ({record.final_output_chars} chars)",
        f"final_diff: {record.final_diff_path} ({record.final_diff_chars} chars, available={record.final_diff_available})",
    ]
    if record.failure_reason:
        lines.append(f"failure: {record.failure_reason}")
    lines.extend(["", "## Model Calls"])
    if record.model_calls:
        for call in record.model_calls:
            status = "cancelled" if call.cancelled else "failed" if call.failed else "completed"
            lines.append(
                f"- turn={call.turn} provider={call.provider} status={status} streamed={call.streamed} "
                f"tools={call.tool_call_count} finish={call.finish_reason or ''} {call.response_artifact}".strip()
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Tools"])
    if record.tool_calls:
        for call in record.tool_calls:
            lines.append(
                f"- {call.tool} {call.tool_call_id} ok={call.ok} blocked={call.blocked} cancelled={call.cancelled} "
                f"output_chars={call.output_chars} {call.output_artifact}".strip()
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Commands"])
    if record.commands:
        for command in record.commands:
            lines.append(
                f"- ok={command.ok} timeout={command.timeout} cancelled={command.cancelled} returncode={command.returncode} "
                f"output_chars={command.output_chars} cmd={command.cmd!r} {command.output_artifact}".strip()
            )
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _model_calls(events: list[Event]) -> list[ModelCallRecord]:
    records: dict[int, dict[str, Any]] = {}
    for event in events:
        data = event.data
        if event.type == "model.call.started":
            turn = int(data.get("model_call_index") or len(records) + 1)
            records.setdefault(turn, {}).update(
                provider=str(data.get("provider") or ""),
                request_artifact=str(data.get("logical_request_artifact") or ""),
            )
            records.setdefault(turn, {}).update(streamed=bool(data.get("stream")))
        elif event.type == "model.call.completed":
            turn = int(data.get("model_call_index") or len(records) + 1)
            records.setdefault(turn, {}).update(
                provider=str(data.get("provider") or ""),
                streamed=bool(data.get("streamed")),
                tool_call_count=int(data.get("tool_call_count") or 0),
                finish_reason=data.get("finish_reason"),
                response_artifact=str(data.get("response_artifact") or ""),
            )
        elif event.type in {"model.call.failed", "model.timeout", "model.idle_timeout"}:
            turn = int(data.get("model_call_index") or len(records) + 1)
            records.setdefault(turn, {}).update(
                provider=str(data.get("provider") or ""),
                failed=True,
                failure_reason=str(data.get("reason") or ""),
            )
        elif event.type == "model.cancelled":
            turn = int(data.get("model_call_index") or len(records) + 1)
            records.setdefault(turn, {}).update(
                provider=str(data.get("provider") or ""),
                cancelled=True,
                failure_reason=str(data.get("reason") or ""),
            )
    return [ModelCallRecord(turn=turn, **values) for turn, values in sorted(records.items())]


def _tool_calls(events: list[Event]) -> list[ToolCallRecord]:
    records: dict[str, dict[str, Any]] = {}
    for event in events:
        data = event.data
        tool_call_id = str(data.get("tool_call_id") or "")
        if not tool_call_id:
            continue
        if event.type == "model.tool_call.assembly.completed":
            records.setdefault(tool_call_id, {}).update(tool=str(data.get("tool") or ""), tool_call_id=tool_call_id)
        elif event.type in {"tool.execution.completed", "tool.execution.failed", "tool.execution.cancelled"}:
            payload = data.get("data") if isinstance(data.get("data"), dict) else {}
            records.setdefault(tool_call_id, {}).update(
                tool=str(data.get("tool") or ""),
                tool_call_id=tool_call_id,
                ok=bool(data.get("ok")),
                blocked=bool(data.get("blocked")),
                cancelled=event.type == "tool.execution.cancelled",
                output_chars=int(data.get("output_chars") or 0),
                output_artifact=str(payload.get("output_artifact") or ""),
            )
    return [ToolCallRecord(**record) for record in records.values()]


def _commands(events: list[Event]) -> list[CommandRecord]:
    records: dict[str, dict[str, Any]] = {}
    for event in events:
        data = event.data
        tool_call_id = str(data.get("tool_call_id") or "")
        if not tool_call_id:
            continue
        if event.type == "command.started":
            records.setdefault(tool_call_id, {}).update(cmd=str(data.get("cmd") or ""))
        elif event.type in {"command.completed", "command.failed", "command.timeout"}:
            records.setdefault(tool_call_id, {}).update(
                ok=bool(data.get("ok")),
                timeout=bool(data.get("timeout")) or event.type == "command.timeout",
                returncode=data.get("returncode"),
                output_chars=int(data.get("output_chars") or 0),
                output_artifact=str(data.get("output_artifact") or ""),
            )
        elif event.type == "command.cancelled":
            records.setdefault(tool_call_id, {}).update(
                ok=False,
                cancelled=True,
                returncode=data.get("returncode"),
                output_chars=int(data.get("output_chars") or 0),
                output_artifact=str(data.get("output_artifact") or ""),
            )
    return [CommandRecord(**record) for record in records.values()]


def _first_event(events: list[Event], event_type: str) -> Event | None:
    return next((event for event in events if event.type == event_type), None)


def _last_event(events: list[Event], event_type: str) -> Event | None:
    return next((event for event in reversed(events) if event.type == event_type), None)


def _status_from_events(events: list[Event]) -> str:
    if any(event.type == "run.cancelled" for event in events):
        return "cancelled"
    if any(event.type == "run.failed" for event in events):
        return "failed"
    if any(event.type == "run.completed" for event in events):
        return "completed"
    return "unknown"


def _failure_from_events(events: list[Event]) -> str:
    failed = _last_event(events, "run.failed")
    return str(failed.data.get("reason") or "") if failed else ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text()
    except OSError:
        return ""
