"""Replay helpers that render traces without executing side effects."""

from __future__ import annotations

from pathlib import Path

from agentd.events import Event, load_events_jsonl


def load_run_events(run_path: Path) -> list[Event]:
    path = run_path if run_path.name == "events.jsonl" else run_path / "events.jsonl"
    return load_events_jsonl(path)


def render_timeline(events: list[Event]) -> str:
    lines = ["# Tinyagent Replay", ""]
    for index, event in enumerate(events, start=1):
        detail = _event_detail(event)
        if detail:
            lines.append(f"{index:04d} {event.time.isoformat()} {event.type} {detail}")
        else:
            lines.append(f"{index:04d} {event.time.isoformat()} {event.type}")
    return "\n".join(lines) + "\n"


def replay_run(run_path: Path) -> str:
    return render_timeline(load_run_events(run_path))


def _event_detail(event: Event) -> str:
    data = event.data
    match event.type:
        case "RunStarted":
            return str(data.get("task", ""))
        case "RunFinished":
            return str(data.get("summary", ""))
        case "RunFailed":
            return str(data.get("reason", ""))
        case "ModelRequest":
            artifacts = [
                data.get("context_artifact"),
                data.get("logical_request_artifact"),
                data.get("http_request_artifact"),
            ]
            artifact_text = " ".join(str(path) for path in artifacts if path)
            return (
                f"provider={data.get('provider')} messages={data.get('message_count')} "
                f"tools={data.get('tool_count')} {artifact_text}"
            ).strip()
        case "ModelResponse":
            return f"tool_calls={data.get('tool_call_count')} finish_reason={data.get('finish_reason')} {data.get('response_artifact')}"
        case "ToolCallRequested" | "ToolCallStarted" | "ToolCallFinished":
            artifact = ""
            if isinstance(data.get("data"), dict):
                artifact = str(data["data"].get("output_artifact") or "")
            return f"{data.get('tool')} {data.get('tool_call_id')} {artifact}".strip()
        case "PolicyDecision":
            return f"{data.get('tool')} allowed={data.get('allowed')} {data.get('reason', '')}"
        case "DiffSnapshot":
            return f"available={data.get('available')} chars={data.get('chars')}"
    return ""
