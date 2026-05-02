"""Deterministic local context compaction."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from agentd.context.types import ArtifactRef, ContextConfig, ContextState
from agentd.output import write_text_artifact
from agentd.state import RunState, ToolStep


def compact_state(state: RunState, config: ContextConfig | None = None) -> str:
    del config
    next_count = state.compaction_count + 1
    context_state = summarize_context_state(state, compaction_count=next_count)
    checkpoint = context_state_to_markdown(context_state)
    artifact = write_text_artifact(
        state,
        f"context-checkpoint-{next_count:04d}.md",
        checkpoint,
        kind="context_checkpoint",
    )
    state.context_state = context_state
    state.context_checkpoint = checkpoint
    state.context_checkpoint_artifact = artifact
    state.context_checkpoint_tool_step_count = len(state.tool_steps)
    state.compaction_count = next_count
    return artifact


def summarize_context_state(state: RunState, *, compaction_count: int | None = None) -> ContextState:
    previous = state.context_state if isinstance(state.context_state, ContextState) else ContextState()
    context_state = ContextState(
        objective=previous.objective or state.task,
        constraints=list(previous.constraints),
        files_seen=dict(previous.files_seen),
        files_changed=dict(previous.files_changed),
        next_steps=list(previous.next_steps),
        compaction_count=compaction_count if compaction_count is not None else previous.compaction_count,
    )
    _collect_event_context(state, context_state)
    _collect_tool_context(state, context_state)
    context_state.known_facts = _dedupe_preserve_order(
        [*previous.known_facts, f"{len(state.tool_steps)} tool step(s) completed before this checkpoint."]
    )[-8:]
    context_state.artifacts = artifact_refs_from_tool_steps(state.tool_steps)
    return context_state


def context_state_to_markdown(context_state: ContextState) -> str:
    return "\n".join(
        [
            f"# Context Checkpoint {context_state.compaction_count}",
            "",
            "## Objective",
            context_state.objective or "Not recorded.",
            "",
            "## Constraints",
            _list_block(context_state.constraints),
            "",
            "## Files Seen",
            _dict_block(context_state.files_seen),
            "",
            "## Files Changed",
            _dict_block(context_state.files_changed),
            "",
            "## Commands Run",
            _list_block(context_state.commands_run),
            "",
            "## Tests Run",
            _list_block(context_state.tests_run),
            "",
            "## Known Facts",
            _list_block(context_state.known_facts),
            "",
            "## Open Issues",
            _list_block(context_state.open_issues),
            "",
            "## Important Artifacts",
            _artifact_block(context_state.artifacts),
            "",
            "## Next Steps",
            _list_block(context_state.next_steps),
            "",
        ]
    )


def artifact_refs_from_tool_steps(steps: Sequence[ToolStep]) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    seen: set[str] = set()
    for step in steps:
        for key in ("output_artifact", "captured_output_artifact"):
            path = step.result.data.get(key)
            if not isinstance(path, str) or path in seen:
                continue
            seen.add(path)
            refs.append(ArtifactRef(path=path, description=_artifact_description(step)))
    return refs


def is_test_command_text(command: str) -> bool:
    return bool(
        re.search(
            r"(^|[;&|]\s*)((uv\s+run\s+)?pytest|python\s+-m\s+pytest|python\s+-m\s+unittest|npm\s+test|pnpm\s+test|yarn\s+test|cargo\s+test|go\s+test)\b",
            command,
        )
    )


def _collect_event_context(state: RunState, context_state: ContextState) -> None:
    commands: list[str] = []
    tests: list[str] = []
    for event in state.events:
        data = event.data
        if event.type == "file.read":
            path = str(data.get("path", ""))
            if path:
                context_state.files_seen[path] = f"read {data.get('line_count', 0)} line(s)"
        elif event.type == "search.completed":
            path = str(data.get("path", "."))
            query = str(data.get("query", ""))
            context_state.files_seen[path] = f"searched for {query!r}"
        elif event.type == "patch.applied":
            for path in data.get("paths", []):
                context_state.files_changed[str(path)] = "changed by apply_patch"
        elif event.type in {"command.completed", "command.failed", "command.timeout"}:
            command = str(data.get("cmd", ""))
            if not command:
                continue
            outcome = _command_outcome(data)
            commands.append(f"{command} -> {outcome}")
            if is_test_command_text(command):
                tests.append(f"{command} -> {outcome}")
    context_state.commands_run = _dedupe_preserve_order(commands)[-20:]
    context_state.tests_run = _dedupe_preserve_order(tests)[-10:]


def _collect_tool_context(state: RunState, context_state: ContextState) -> None:
    issues: list[str] = []
    for step in state.tool_steps:
        if step.call.name == "apply_patch":
            for path in step.result.data.get("paths", []):
                context_state.files_changed[str(path)] = "changed by apply_patch" if step.result.ok else "attempted apply_patch"
        if not step.result.ok:
            issues.append(f"{step.call.name} {step.call.id}: {_first_line(step.result.output)}")
    context_state.open_issues = issues[-8:]


def _command_outcome(data: dict[str, Any]) -> str:
    if data.get("timeout"):
        return "timed out"
    if data.get("ok"):
        return "ok"
    return f"exit {data.get('returncode')}"


def _artifact_description(step: ToolStep) -> str:
    if step.call.name == "shell":
        cmd = str(step.call.args.get("cmd", ""))
        return f"shell output for {cmd[:120]}"
    if step.call.name == "apply_patch":
        paths = step.result.data.get("paths", [])
        return f"apply_patch output for {', '.join(str(path) for path in paths)}"
    return f"{step.call.name} output"


def _first_line(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line[:240]


def _dedupe_preserve_order(values: Sequence[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _list_block(values: Sequence[str]) -> str:
    if not values:
        return "- None recorded."
    return "\n".join(f"- {value}" for value in values)


def _dict_block(values: dict[str, str]) -> str:
    if not values:
        return "- None recorded."
    return "\n".join(f"- {path}: {description}" for path, description in sorted(values.items()))


def _artifact_block(refs: Sequence[ArtifactRef]) -> str:
    if not refs:
        return "- None recorded."
    return "\n".join(f"- {ref.path}: {ref.description}" if ref.description else f"- {ref.path}" for ref in refs)
