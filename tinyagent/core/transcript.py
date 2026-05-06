"""Canonical run transcript records."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

TranscriptItemKind = Literal["model_response", "tool_call", "tool_result", "finish_gate", "compaction"]


@dataclass(frozen=True)
class TranscriptItem:
    kind: TranscriptItemKind
    id: str
    turn_id: str | None = None
    model_call_id: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    summary: str = ""
    artifact_refs: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Transcript:
    items: list[TranscriptItem] = field(default_factory=list)
    pending_tool_call_ids: set[str] = field(default_factory=set)

    def record_model_response(
        self,
        *,
        item_id: str,
        turn_id: str | None,
        model_call_id: str,
        provider: str,
        content_length: int,
        finish_reason: str | None,
        tool_call_count: int,
        response_artifact: str | None = None,
    ) -> None:
        refs = (response_artifact,) if response_artifact else ()
        self.items.append(
            TranscriptItem(
                kind="model_response",
                id=item_id,
                turn_id=turn_id,
                model_call_id=model_call_id,
                summary=f"{provider} response with {tool_call_count} tool call(s)",
                artifact_refs=refs,
                data={
                    "provider": provider,
                    "content_length": content_length,
                    "finish_reason": finish_reason,
                    "tool_call_count": tool_call_count,
                },
            )
        )

    def record_tool_call(
        self,
        *,
        item_id: str,
        turn_id: str | None,
        model_call_id: str | None,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> None:
        self.pending_tool_call_ids.add(tool_call_id)
        self.items.append(
            TranscriptItem(
                kind="tool_call",
                id=item_id,
                turn_id=turn_id,
                model_call_id=model_call_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                summary=f"{tool_name} requested",
                data={"args": args},
            )
        )

    def record_tool_result(
        self,
        *,
        item_id: str,
        turn_id: str | None,
        tool_call_id: str,
        tool_name: str,
        ok: bool,
        summary: str,
        failure_kind: str | None,
        artifact_refs: tuple[str, ...] = (),
        synthetic: bool = False,
        data: dict[str, Any] | None = None,
    ) -> None:
        if not tool_call_id:
            raise ValueError("Transcript tool result requires a call id.")
        self.pending_tool_call_ids.discard(tool_call_id)
        self.items.append(
            TranscriptItem(
                kind="tool_result",
                id=item_id,
                turn_id=turn_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                summary=summary,
                artifact_refs=artifact_refs,
                data={
                    "ok": ok,
                    "failure_kind": failure_kind,
                    "synthetic": synthetic,
                    **(data or {}),
                },
            )
        )

    def record_finish_gate(self, *, item_id: str, turn_id: str | None, reason: str, injected_message: str | None) -> None:
        self.items.append(
            TranscriptItem(
                kind="finish_gate",
                id=item_id,
                turn_id=turn_id,
                summary=reason,
                data={"reason": reason, "injected_message": injected_message},
            )
        )

    def record_compaction(
        self,
        *,
        item_id: str,
        turn_id: str | None,
        compaction_count: int,
        checkpoint_artifact: str | None,
    ) -> None:
        refs = (checkpoint_artifact,) if checkpoint_artifact else ()
        self.items.append(
            TranscriptItem(
                kind="compaction",
                id=item_id,
                turn_id=turn_id,
                summary=f"checkpoint {compaction_count}",
                artifact_refs=refs,
                data={"compaction_count": compaction_count, "checkpoint_artifact": checkpoint_artifact},
            )
        )

    def validate_complete(self) -> None:
        if self.pending_tool_call_ids:
            pending = ", ".join(sorted(self.pending_tool_call_ids))
            raise ValueError(f"Transcript has tool calls without results: {pending}")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_json_dict() for item in self.items],
            "pending_tool_call_ids": sorted(self.pending_tool_call_ids),
        }
