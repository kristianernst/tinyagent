"""Replay helpers that render traces without executing side effects."""

from __future__ import annotations

from pathlib import Path

from agentd.events import Event, load_events_jsonl


def load_run_events(run_path: Path) -> list[Event]:
    path = run_path if run_path.name == "events.jsonl" else run_path / "events.jsonl"
    return load_events_jsonl(path)


def render_timeline(events: list[Event]) -> str:
    lines = ["# Tinyagent Replay", ""]
    for event in events:
        detail = _event_detail(event)
        seq = event.seq if event.seq > 0 else 0
        if detail:
            lines.append(f"{seq:04d} {event.time.isoformat()} {event.type} {detail}")
        else:
            lines.append(f"{seq:04d} {event.time.isoformat()} {event.type}")
    return "\n".join(lines) + "\n"


def replay_run(run_path: Path) -> str:
    return render_timeline(load_run_events(run_path))


def _event_detail(event: Event) -> str:
    data = event.data
    match event.type:
        case "run.started":
            return str(data.get("task", ""))
        case "run.completed":
            return f"turns={data.get('turn_count')} tools={data.get('tool_call_count')}"
        case "run.failed":
            return str(data.get("reason", ""))
        case "run.cancel.requested":
            return f"{data.get('reason', '')} current={data.get('current_step_kind') or ''}:{data.get('current_step_id') or ''}".strip()
        case "run.cancelled":
            return f"{data.get('reason', '')} turns={data.get('turn_count')} tools={data.get('tool_call_count')}".strip()
        case "turn.started" | "turn.completed" | "turn.interrupted" | "turn.failed":
            return f"{data.get('turn_id', event.turn_id or '')} status={data.get('status', '')}".strip()
        case (
            "step.started"
            | "step.completed"
            | "step.failed"
            | "step.cancel.requested"
            | "step.cancelled"
            | "step.timeout"
            | "step.idle_timeout"
        ):
            return f"{data.get('step_kind')} {data.get('step_id')} {data.get('reason', '')}".strip()
        case "workspace.boundary":
            return f"mode={data.get('mode')} effective={data.get('effective_mode')} root={data.get('root')}"
        case "workspace.dirty.detected":
            return f"dirty files={len(data.get('status_short') or [])}"
        case "worktree.created":
            return str(data.get("path") or "")
        case "model.message.completed":
            return f"{data.get('role', 'assistant')} {data.get('content_chars')} chars {data.get('output_path', '')}".strip()
        case "model.call.started":
            artifacts = [
                data.get("context_artifact"),
                data.get("context_report_artifact"),
                data.get("logical_request_artifact"),
                data.get("http_request_artifact"),
            ]
            artifact_text = " ".join(str(path) for path in artifacts if path)
            return (
                f"provider={data.get('provider')} messages={data.get('message_count')} "
                f"tools={data.get('tool_count')} {artifact_text}"
            ).strip()
        case "model.call.completed":
            return (
                f"provider={data.get('provider')} model_call={data.get('model_call_index')} "
                f"tool_calls={data.get('tool_call_count')} finish_reason={data.get('finish_reason')} "
                f"{data.get('response_artifact') or ''}"
            )
        case "model.call.failed" | "model.timeout" | "model.idle_timeout":
            return f"provider={data.get('provider')} {data.get('reason', '')}"
        case "model.cancelled":
            return f"provider={data.get('provider')} model_call={data.get('model_call_index')} {data.get('reason', '')}".strip()
        case "model.usage":
            total = data.get("total_tokens")
            return f"provider={data.get('provider')} total_tokens={total}" if total is not None else f"provider={data.get('provider')}"
        case "model.tool_call.assembly.started" | "model.tool_call.assembly.completed" | "model.tool_call.assembly.failed":
            return f"{data.get('tool')} {data.get('tool_call_id')} {data.get('reason', '')}".strip()
        case (
            "tool.execution.started"
            | "tool.execution.completed"
            | "tool.execution.failed"
            | "tool.execution.cancelled"
            | "tool.execution.blocked"
        ):
            artifact = str(data.get("artifact_path") or "")
            if isinstance(data.get("data"), dict):
                artifact = artifact or str(data["data"].get("context_artifact") or data["data"].get("output_artifact") or "")
            return f"{data.get('tool')} {data.get('tool_call_id')} {artifact}".strip()
        case "context.report.written":
            return f"model_call={data.get('model_call_index')} {data.get('context_report_artifact') or ''}".strip()
        case "contextfs.index.updated":
            return str(data.get("path") or "")
        case "contextfs.artifact.written":
            return f"{data.get('tool')} {data.get('tool_call_id')} {data.get('path')}".strip()
        case "command.cancelled":
            return f"{data.get('cmd')} returncode={data.get('returncode')} {data.get('output_artifact') or ''}".strip()
        case "policy.evaluated":
            return f"{data.get('tool')} kind={data.get('kind')} {data.get('reason', '')}"
        case "approval.requested" | "approval.resolved" | "approval.expired":
            return f"{data.get('approval_id')} {data.get('decision', '')} {data.get('reason', '')}".strip()
        case "diff.finalized":
            return f"available={data.get('available')} chars={data.get('chars')}"
        case "artifact.materialized":
            return str(data.get("path") or "")
    return ""
