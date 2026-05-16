"""Run graph helpers for forks and child run summaries."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from tinyagent.core.events import Event, load_events_jsonl
from tinyagent.core.output import write_text_artifact
from tinyagent.core.state import RunState
from tinyagent.core.token_utils import estimate_tokens


def fork_run(run_path: Path, at_event_id: str, output_dir: Path | None = None) -> Path:
    run_path = run_path.expanduser().resolve()
    events_path = run_path if run_path.name == "events.jsonl" else run_path / "events.jsonl"
    events = load_events_jsonl(events_path)
    event = _find_event(events, at_event_id)
    if event is None:
        raise ValueError(f"Event not found for fork: {at_event_id}")
    destination = (output_dir or run_path.with_name(f"{run_path.name}-fork-{event.seq:04d}")).expanduser().resolve()
    if destination.exists():
        raise ValueError(f"Fork output directory already exists: {destination}")
    destination.mkdir(parents=True)
    metadata = {
        "parent_run_id": event.run_id,
        "parent_event_id": event.id,
        "parent_event_seq": event.seq,
        "source_run_path": str(run_path),
    }
    (destination / "fork.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    summary = "\n".join(
        [
            "# Fork Summary",
            "",
            f"parent_run_id: {event.run_id}",
            f"parent_event_id: {event.id}",
            f"parent_event_seq: {event.seq}",
            f"parent_event_type: {event.type}",
            "",
        ]
    )
    (destination / "summary.md").write_text(summary)
    return destination


def record_child_summary(parent: RunState, child: RunState) -> str:
    summary = "\n".join(
        [
            "# Child Run Summary",
            "",
            f"child_run_id: {child.run_id}",
            f"status: {child.status}",
            f"output_dir: {child.output_dir}",
            f"final_output_tokens: {estimate_tokens(child.final_output)}",
            "",
            child.final_output,
            "",
        ]
    )
    artifact = write_text_artifact(parent, f"child-{child.run_id}-summary.md", summary, kind="child_summary")
    event_type = "child_run.completed" if not child.failed and not child.cancelled else "child_run.failed"
    parent.emit(
        event_type,
        {
            "child_run_id": child.run_id,
            "status": child.status,
            "summary_artifact": artifact,
            "output_dir": str(child.output_dir),
        },
    )
    return artifact


def copy_run_stub(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("events.jsonl", "metrics.json", "final.md"):
        src = source / name
        if src.exists():
            shutil.copy2(src, destination / name)


def _find_event(events: list[Event], event_id: str) -> Event | None:
    for event in events:
        if event.id == event_id or str(event.seq) == event_id or f"{event.seq:04d}" == event_id:
            return event
    return None
