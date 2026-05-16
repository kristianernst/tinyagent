"""Durable controller-level conversation ledger."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from tinyagent.core.artifacts import tool_result_artifact_refs
from tinyagent.core.events import json_safe, utc_now
from tinyagent.core.state import Message, RunState
from tinyagent.core.token_utils import estimate_tokens

ConversationStatus = Literal["open", "closed", "archived"]


@dataclass(frozen=True)
class ConversationRecord:
    conversation_id: str
    workspace: str
    title: str
    status: ConversationStatus = "open"
    active_turn_id: str | None = None
    created_at: str = field(default_factory=lambda: utc_now().isoformat().replace("+00:00", "Z"))
    updated_at: str = field(default_factory=lambda: utc_now().isoformat().replace("+00:00", "Z"))

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConversationStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.home() / ".tinyagent" / "conversations").expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, *, workspace: Path, title: str = "", conversation_id: str | None = None) -> ConversationRecord:
        resolved_id = conversation_id or f"conv_{uuid4().hex}"
        record = ConversationRecord(
            conversation_id=resolved_id,
            workspace=str(workspace.expanduser().resolve()),
            title=title,
        )
        path = self.conversation_path(resolved_id)
        path.mkdir(parents=True, exist_ok=False)
        self._write_conversation(record)
        return record

    def ensure(self, *, workspace: Path, conversation_id: str, title: str = "") -> ConversationRecord:
        try:
            return self.load(conversation_id)
        except FileNotFoundError:
            return self.create(workspace=workspace, title=title, conversation_id=conversation_id)

    def load(self, conversation_id: str) -> ConversationRecord:
        data = json.loads((self.conversation_path(conversation_id) / "conversation.json").read_text())
        return ConversationRecord(**data)

    def archive(self, conversation_id: str) -> ConversationRecord:
        record = self.load(conversation_id)
        archived = ConversationRecord(
            conversation_id=record.conversation_id,
            workspace=record.workspace,
            title=record.title,
            status="archived",
            active_turn_id=record.active_turn_id,
            created_at=record.created_at,
            updated_at=_now(),
        )
        self._write_conversation(archived)
        return archived

    def list(self, *, workspace: Path | None = None) -> list[dict[str, Any]]:
        workspace_filter = str(workspace.expanduser().resolve()) if workspace is not None else None
        conversations: list[dict[str, Any]] = []
        for path in sorted(self.root.iterdir()):
            if not path.is_dir() or not (path / "conversation.json").exists():
                continue
            try:
                record = self.load(path.name)
            except (OSError, ValueError, json.JSONDecodeError, TypeError):
                continue
            if workspace_filter is not None and record.workspace != workspace_filter:
                continue
            turns = self.turns(record.conversation_id)
            turn_ids = {str(turn.get("turn_id")) for turn in turns if turn.get("turn_id")}
            last_turn = turns[-1] if turns else {}
            conversations.append(
                {
                    **record.to_json_dict(),
                    "turn_count": len(turn_ids),
                    "last_run_id": last_turn.get("run_id"),
                    "last_turn_status": last_turn.get("status"),
                }
            )
        return sorted(conversations, key=lambda item: str(item.get("updated_at") or ""), reverse=True)

    def record_turn_started(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        run_id: str,
        run_path: Path,
        workspace: Path,
        user_message: Message,
        parent_turn_id: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "type": "turn.started",
            "conversation_id": conversation_id,
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
        self._append_turn(conversation_id, entry)
        self._touch(conversation_id, active_turn_id=turn_id, title=str(user_message.content)[:80])
        return entry

    def record_turn(
        self,
        *,
        conversation_id: str,
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
            "conversation_id": conversation_id,
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
                "content_tokens": estimate_tokens(content),
            },
            "tool_summary": tool_summary or [],
            "token_estimate": estimate_tokens(str(user_message.content or "")) + estimate_tokens(content),
            "created_at": _now(),
        }
        self._append_turn(conversation_id, entry)
        self._touch(conversation_id, active_turn_id=turn_id, title=str(user_message.content)[:80])
        return entry

    def record_run_turn(
        self,
        *,
        conversation_id: str,
        turn_id: str,
        user_content: str,
        state: RunState,
        parent_turn_id: str | None = None,
    ) -> dict[str, Any]:
        return self.record_turn(
            conversation_id=conversation_id,
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

    def turns(self, conversation_id: str) -> list[dict[str, Any]]:
        path = self.conversation_path(conversation_id) / "turns.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def prior_messages(self, conversation_id: str, *, limit: int = 12) -> tuple[Message, ...]:
        messages: list[Message] = []
        completed_turns = [turn for turn in self.turns(conversation_id) if turn.get("type") == "turn.completed"]
        for turn in completed_turns[-limit:]:
            user = turn.get("user_message") if isinstance(turn.get("user_message"), dict) else {}
            assistant = turn.get("assistant_message") if isinstance(turn.get("assistant_message"), dict) else {}
            if user.get("content"):
                messages.append(
                    Message(
                        role="user",
                        content=user["content"],
                        meta={"conversation_id": conversation_id, "turn_id": turn.get("turn_id")},
                    )
                )
            content = _assistant_content(turn, assistant)
            if content:
                messages.append(
                    Message(
                        role="assistant",
                        content=content,
                        meta={"conversation_id": conversation_id, "turn_id": turn.get("turn_id")},
                    )
                )
        return tuple(messages)

    def conversation_path(self, conversation_id: str) -> Path:
        if not conversation_id or "/" in conversation_id or "\\" in conversation_id or conversation_id.startswith("."):
            raise ValueError(f"invalid conversation_id: {conversation_id}")
        return self.root / conversation_id

    def _append_turn(self, conversation_id: str, entry: dict[str, Any]) -> None:
        with (self.conversation_path(conversation_id) / "turns.jsonl").open("a") as file:
            file.write(json.dumps(entry, sort_keys=True) + "\n")

    def _touch(self, conversation_id: str, *, active_turn_id: str, title: str) -> None:
        record = self.load(conversation_id)
        self._write_conversation(
            ConversationRecord(
                conversation_id=record.conversation_id,
                workspace=record.workspace,
                title=record.title or title,
                status=record.status,
                active_turn_id=active_turn_id,
                created_at=record.created_at,
                updated_at=_now(),
            )
        )

    def _write_conversation(self, record: ConversationRecord) -> None:
        path = self.conversation_path(record.conversation_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "conversation.json").write_text(json.dumps(record.to_json_dict(), indent=2, sort_keys=True) + "\n")


def _tool_summary(state: RunState) -> list[dict[str, Any]]:
    summary = []
    for step in state.tool_steps:
        summary.append(
            {
                "tool_call_id": step.call.id,
                "tool": step.call.name,
                "ok": step.result.ok,
                "summary": step.result.summary or _preview(step.result.output),
                "artifact_refs": list(tool_result_artifact_refs(step.result)),
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


def _preview(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def _now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")
