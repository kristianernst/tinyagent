"""File-backed coordination primitives for multi-run product workflows."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

COORDINATION_DIR = Path(".tinyagent") / "coordination"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class CoordinationSession:
    session_id: str
    path: Path
    state_path: Path
    tasks_path: Path
    claims_path: Path
    handoffs_path: Path
    runs_path: Path


class CoordinationStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.expanduser().resolve()
        self.root = self.workspace / COORDINATION_DIR

    def create(self, session_id: str | None = None, *, state: str = "") -> CoordinationSession:
        session = self.session(session_id or f"coord_{uuid4().hex}")
        session.path.mkdir(parents=True, exist_ok=False)
        session.runs_path.mkdir()
        session.state_path.write_text(state or "# Coordination State\n")
        session.tasks_path.write_text("")
        session.claims_path.write_text("")
        session.handoffs_path.write_text("")
        return session

    def session(self, session_id: str) -> CoordinationSession:
        _validate_id(session_id, "session")
        path = (self.root / session_id).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError(f"coordination session escapes root: {session_id}") from exc
        return CoordinationSession(
            session_id=session_id,
            path=path,
            state_path=path / "state.md",
            tasks_path=path / "tasks.jsonl",
            claims_path=path / "claims.jsonl",
            handoffs_path=path / "handoffs.jsonl",
            runs_path=path / "runs",
        )

    def create_task(self, session_id: str, summary: str, *, task_id: str | None = None) -> dict[str, object]:
        session = self.session(session_id)
        payload = {
            "type": "task.created",
            "task_id": task_id or f"task_{uuid4().hex}",
            "summary": summary,
            "created_at": _now(),
        }
        _validate_id(str(payload["task_id"]), "task")
        _append_jsonl(session.tasks_path, payload)
        return payload

    def claim_task(self, session_id: str, task_id: str, run_id: str) -> dict[str, object]:
        _validate_id(task_id, "task")
        _validate_id(run_id, "run")
        session = self.session(session_id)
        payload = {"type": "task.claimed", "task_id": task_id, "run_id": run_id, "created_at": _now()}
        _append_jsonl(session.claims_path, payload)
        return payload

    def handoff(self, session_id: str, *, from_run: str, to_run: str, summary: str) -> dict[str, object]:
        _validate_id(from_run, "run")
        _validate_id(to_run, "run")
        session = self.session(session_id)
        payload = {
            "type": "handoff",
            "from": from_run,
            "to": to_run,
            "summary": summary,
            "created_at": _now(),
        }
        _append_jsonl(session.handoffs_path, payload)
        return payload

    def write_state(self, session_id: str, text: str) -> Path:
        session = self.session(session_id)
        session.state_path.parent.mkdir(parents=True, exist_ok=True)
        session.state_path.write_text(text)
        return session.state_path

    def record_run(self, session_id: str, *, run_id: str, task_id: str | None = None, summary: str = "") -> Path:
        _validate_id(run_id, "run")
        if task_id is not None:
            _validate_id(task_id, "task")
        session = self.session(session_id)
        session.runs_path.mkdir(parents=True, exist_ok=True)
        path = session.runs_path / f"{run_id}.json"
        path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "task_id": task_id or "",
                    "summary": summary,
                    "created_at": _now(),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return path

    def events(self, session_id: str) -> list[dict[str, object]]:
        session = self.session(session_id)
        return [
            *_read_jsonl(session.tasks_path),
            *_read_jsonl(session.claims_path),
            *_read_jsonl(session.handoffs_path),
        ]


def _append_jsonl(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as file:
        file.write(json.dumps(payload, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _validate_id(value: str, label: str) -> None:
    if not ID_PATTERN.fullmatch(value):
        raise ValueError(f"Invalid {label} id: {value}")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
