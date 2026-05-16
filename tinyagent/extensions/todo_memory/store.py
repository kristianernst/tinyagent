"""Run-scoped working todo store."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tinyagent.core.events import utc_now
from tinyagent.core.state import RunState
from tinyagent.core.token_utils import token_budget_to_text_limit
from tinyagent.extensions.todo_memory.types import TodoItem, TodoState

TODO_JSON = Path("context/memory/todo.json")
TODO_MD = Path("context/memory/todo.md")
MAX_TODO_ITEMS = 100
MAX_TODO_ID_TOKENS = 20
MAX_TODO_TEXT_TOKENS = 125
MAX_TODO_NOTES_TOKENS = 1_000
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


class TodoStore:
    def read(self, state: RunState) -> TodoState:
        path = state.output_dir / TODO_JSON
        if not path.exists():
            return TodoState()
        return TodoState.from_dict(json.loads(path.read_text()))

    def write(self, state: RunState, items: list[dict[str, object]], *, notes: str = "") -> TodoState:
        now = utc_now().isoformat().replace("+00:00", "Z")
        current = {item.id: item for item in self.read(state).items}
        next_items: list[TodoItem] = []
        reserved_ids = {
            _safe_id(str(raw.get("id") or ""))
            for raw in items
            if isinstance(raw.get("id"), str) and str(raw.get("id") or "").strip()
        }
        used_ids: set[str] = set()
        for index, raw in enumerate(items[:MAX_TODO_ITEMS], start=1):
            text = str(raw.get("text") or "").strip()[: token_budget_to_text_limit(MAX_TODO_TEXT_TOKENS)]
            if not text:
                continue
            raw_id = str(raw.get("id") or "").strip()
            item_id = _safe_id(raw_id) if raw_id else _generated_id(index, reserved_ids | used_ids)
            if item_id in used_ids:
                item_id = _generated_id(index, reserved_ids | used_ids)
            used_ids.add(item_id)
            previous = current.get(item_id)
            status = "done" if str(raw.get("status") or "open") == "done" else "open"
            next_items.append(
                TodoItem(
                    id=item_id,
                    text=text,
                    status=status,
                    created_at=previous.created_at if previous else now,
                    updated_at=now,
                    source="model",
                )
            )
        todo = TodoState(items=tuple(next_items), notes=str(notes)[: token_budget_to_text_limit(MAX_TODO_NOTES_TOKENS)])
        _atomic_write(state.output_dir / TODO_JSON, json.dumps(todo.to_json_dict(), indent=2, sort_keys=True) + "\n")
        markdown = render_todo_markdown(todo)
        _atomic_write(state.output_dir / TODO_MD, markdown)
        state.emit(
            "contextfs.artifact.written",
            {
                "path": TODO_MD.as_posix(),
                "kind": "working_memory",
                "tool_call_id": "",
                "tool": "todo_memory",
                "bytes": len(markdown.encode()),
            },
        )
        return todo


def render_todo_markdown(todo: TodoState) -> str:
    lines = ["# Working Todo", ""]
    if todo.items:
        for item in todo.items:
            mark = "x" if item.status == "done" else " "
            lines.append(f"- [{mark}] {item.id} {item.text}")
    else:
        lines.append("No todo items.")
    lines.extend(["", "## Notes", "", todo.notes or ""])
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content)
    temp.replace(path)


def _safe_id(value: str) -> str:
    cleaned = _SAFE_ID_RE.sub("_", value)[: token_budget_to_text_limit(MAX_TODO_ID_TOKENS)].strip("._:-")
    return cleaned or "todo"


def _generated_id(index: int, used_ids: set[str]) -> str:
    candidate = f"todo_{index}"
    while candidate in used_ids:
        index += 1
        candidate = f"todo_{index}"
    return candidate
