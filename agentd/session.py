"""Durable controller-level session ledger."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from agentd.events import json_safe, utc_now
from agentd.state import Message, RunState

SessionStatus = Literal["open", "closed"]


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    workspace: str
    title: str
    status: SessionStatus = "open"
    active_turn_id: str | None = None
    created_at: str = field(default_factory=lambda: utc_now().isoformat().replace("+00:00", "Z"))
    updated_at: str = field(default_factory=lambda: utc_now().isoformat().replace("+00:00", "Z"))

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


class SessionStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.home() / ".tinyagent" / "sessions").expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, *, workspace: Path, title: str = "", session_id: str | None = None) -> SessionRecord:
        resolved_id = session_id or f"sess_{uuid4().hex}"
        record = SessionRecord(
            session_id=resolved_id,
            workspace=str(workspace.expanduser().resolve()),
            title=title,
        )
        path = self.session_path(resolved_id)
        path.mkdir(parents=True, exist_ok=False)
        self._write_session(record)
        self._append_index(record)
        return record

    def ensure(self, *, workspace: Path, session_id: str, title: str = "") -> SessionRecord:
        try:
            return self.load(session_id)
        except FileNotFoundError:
            return self.create(workspace=workspace, title=title, session_id=session_id)

    def load(self, session_id: str) -> SessionRecord:
        data = json.loads((self.session_path(session_id) / "session.json").read_text())
        return SessionRecord(**data)

    def list(self, *, workspace: Path | None = None) -> list[dict[str, Any]]:
        workspace_filter = str(workspace.expanduser().resolve()) if workspace is not None else None
        sessions: list[dict[str, Any]] = []
        for path in sorted(self.root.iterdir()):
            if not path.is_dir() or not (path / "session.json").exists():
                continue
            try:
                record = self.load(path.name)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if workspace_filter is not None and record.workspace != workspace_filter:
                continue
            turns = self.turns(record.session_id)
            turn_ids = {str(turn.get("turn_id")) for turn in turns if turn.get("turn_id")}
            last_turn = turns[-1] if turns else {}
            sessions.append(
                {
                    **record.to_json_dict(),
                    "turn_count": len(turn_ids),
                    "last_run_id": last_turn.get("run_id"),
                    "last_turn_status": last_turn.get("status"),
                }
            )
        return sorted(sessions, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def record_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        run_id: str,
        run_path: Path,
        workspace: Path,
        user_message: Message,
        assistant_message: Message,
        parent_turn_id: str | None = None,
        tool_summary: list[dict[str, Any]] | None = None,
        status: str = "completed",
    ) -> dict[str, Any]:
        content = str(assistant_message.content or "")
        entry = {
            "type": "turn.completed",
            "session_id": session_id,
            "turn_id": turn_id,
            "run_id": run_id,
            "parent_turn_id": parent_turn_id,
            "workspace": str(workspace.expanduser().resolve()),
            "run_path": str(run_path.expanduser().resolve()),
            "status": status,
            "user_message": {
                "id": f"{turn_id}-user",
                "role": user_message.role,
                "content": json_safe(user_message.content),
            },
            "assistant_message": {
                "id": f"{turn_id}-assistant",
                "role": assistant_message.role,
                "content_artifact": "final.md",
                "content_preview": _preview(content),
                "content_chars": len(content),
            },
            "tool_summary": tool_summary or [],
            "token_estimate": _estimate_tokens(str(user_message.content or "")) + _estimate_tokens(content),
            "created_at": _now(),
        }
        with (self.session_path(session_id) / "turns.jsonl").open("a") as file:
            file.write(json.dumps(entry, sort_keys=True) + "\n")
        record = self.load(session_id)
        self._write_session(
            SessionRecord(
                session_id=record.session_id,
                workspace=record.workspace,
                title=record.title or str(user_message.content)[:80],
                status=record.status,
                active_turn_id=turn_id,
                created_at=record.created_at,
                updated_at=_now(),
            )
        )
        return entry

    def record_turn_started(
        self,
        *,
        session_id: str,
        turn_id: str,
        run_id: str,
        run_path: Path,
        workspace: Path,
        user_message: Message,
        parent_turn_id: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "type": "turn.started",
            "session_id": session_id,
            "turn_id": turn_id,
            "run_id": run_id,
            "parent_turn_id": parent_turn_id,
            "workspace": str(workspace.expanduser().resolve()),
            "run_path": str(run_path.expanduser().resolve()),
            "status": "running",
            "user_message": {
                "id": f"{turn_id}-user",
                "role": user_message.role,
                "content": json_safe(user_message.content),
            },
            "created_at": _now(),
        }
        with (self.session_path(session_id) / "turns.jsonl").open("a") as file:
            file.write(json.dumps(entry, sort_keys=True) + "\n")
        record = self.load(session_id)
        self._write_session(
            SessionRecord(
                session_id=record.session_id,
                workspace=record.workspace,
                title=record.title or str(user_message.content)[:80],
                status=record.status,
                active_turn_id=turn_id,
                created_at=record.created_at,
                updated_at=_now(),
            )
        )
        return entry

    def record_run_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        user_content: str,
        state: RunState,
        parent_turn_id: str | None = None,
    ) -> dict[str, Any]:
        return self.record_turn(
            session_id=session_id,
            turn_id=turn_id,
            run_id=state.run_id,
            run_path=state.output_dir,
            workspace=state.workspace.root,
            user_message=Message(role="user", content=user_content),
            assistant_message=Message(role="assistant", content=state.final_output),
            parent_turn_id=parent_turn_id,
            tool_summary=_tool_summary(state),
            status="cancelled" if state.cancelled else "failed" if state.failed else "completed",
        )

    def turns(self, session_id: str) -> list[dict[str, Any]]:
        path = self.session_path(session_id) / "turns.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def prior_messages(self, session_id: str, *, limit: int = 12) -> tuple[Message, ...]:
        messages: list[Message] = []
        completed_turns = [turn for turn in self.turns(session_id) if turn.get("type") == "turn.completed"]
        for turn in completed_turns[-limit:]:
            user = turn.get("user_message") if isinstance(turn.get("user_message"), dict) else {}
            assistant = turn.get("assistant_message") if isinstance(turn.get("assistant_message"), dict) else {}
            if user.get("content"):
                messages.append(
                    Message(
                        role="user",
                        content=user["content"],
                        meta={"session_id": session_id, "turn_id": turn.get("turn_id")},
                    )
                )
            content = _assistant_content(turn, assistant)
            if content:
                messages.append(
                    Message(
                        role="assistant",
                        content=content,
                        meta={"session_id": session_id, "turn_id": turn.get("turn_id")},
                    )
                )
        return tuple(messages)

    def session_path(self, session_id: str) -> Path:
        if not session_id or "/" in session_id or "\\" in session_id or session_id.startswith("."):
            raise ValueError(f"invalid session_id: {session_id}")
        return self.root / session_id

    def _write_session(self, record: SessionRecord) -> None:
        path = self.session_path(record.session_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "session.json").write_text(json.dumps(record.to_json_dict(), indent=2, sort_keys=True) + "\n")

    def _append_index(self, record: SessionRecord) -> None:
        with (self.root / "index.jsonl").open("a") as file:
            file.write(json.dumps(record.to_json_dict(), sort_keys=True) + "\n")


def _tool_summary(state: RunState) -> list[dict[str, Any]]:
    summary = []
    for step in state.tool_steps:
        artifact_refs = [value for value in (step.result.artifact_path, step.result.data.get("output_artifact")) if value]
        summary.append(
            {
                "tool_call_id": step.call.id,
                "tool": step.call.name,
                "ok": step.result.ok,
                "summary": step.result.summary or _preview(step.result.output),
                "artifact_refs": artifact_refs,
            }
        )
    return summary


def _assistant_content(turn: dict[str, Any], assistant: dict[str, Any]) -> str:
    run_path = turn.get("run_path")
    artifact = assistant.get("content_artifact")
    if isinstance(run_path, str) and isinstance(artifact, str) and artifact:
        path = Path(run_path) / artifact
        if path.exists():
            text = path.read_text()
            if text.startswith("# Final output\n\n"):
                text = text.removeprefix("# Final output\n\n")
            return text.strip()
    preview = assistant.get("content_preview")
    return str(preview or "")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _preview(text: str, limit: int = 240) -> str:
    clean = text.strip().replace("\n", " ")
    return clean if len(clean) <= limit else clean[: limit - 1] + "..."


def _now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")
