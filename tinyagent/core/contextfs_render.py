"""Pure render plan for ContextFS files."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tinyagent.core.context.builder import render_environment_context

if TYPE_CHECKING:
    from tinyagent.core.state import RunState, ToolStep


STATIC_CONTEXT_FILE_RELS = (
    "context/INDEX.md",
    "context/task.md",
    "context/environment.md",
    "context/current_status.md",
    "context/current_diff.patch",
    "context/current_diff.md",
    "context/last_failure.md",
    "context/observations.md",
    "context/transcript.md",
    "context/history/compacted.md",
    "context/history/summary.md",
    "context/history/raw.jsonl",
    "context/tools/INDEX.md",
    "context/diffs/INDEX.md",
)
OPTIONAL_CONTEXT_FILE_RELS = ("context/memory/todo.md",)

TOOL_CONTEXT_DESCRIPTIONS = {
    "read_file": "Workspace file reads. Long reads are artifact-backed under ContextFS.",
    "context_search": "Dynamic context search results across registered context sources.",
    "context_read": "Dynamic context refs loaded from registered context sources.",
    "search_code": "Workspace code and docs search results.",
    "apply_patch": "Patch edit outputs and changed-file evidence.",
    "str_replace_edit": "String replacement edit outputs and changed-file evidence.",
    "write_file": "Whole-file write outputs and changed-file evidence.",
    "shell": "Shell command outputs stored under ContextFS when long or otherwise artifact-backed.",
}


@dataclass(frozen=True)
class ContextIndexEntry:
    path: str
    section: str
    description: str
    read_hint: str = ""


@dataclass(frozen=True)
class ContextFileSpec:
    rel: str
    section: str
    title: str
    description: str
    render: Callable[["RunState"], str]
    include_in_index: bool = True
    static_allowed: bool = True

    def index_entry(self) -> ContextIndexEntry:
        return ContextIndexEntry(path=self.rel, section=self.section, description=self.description)


@dataclass(frozen=True)
class RenderedContextFile:
    rel: str
    content: str


@dataclass(frozen=True)
class ContextRenderHelpers:
    context_ref: Callable[[str | Path], str]
    safe_recovery_artifact_ref: Callable[[object], str | None]
    tool_artifact_refs: Callable[["ToolStep"], tuple[str, ...]]
    safe_transcript_refs: Callable[[tuple[str, ...]], str]
    sanitize_value: Callable[[str], str]
    sanitize_data: Callable[[Any], Any]
    repo_status_text: Callable[[], str]
    repo_diff_text: Callable[[], str]
    raw_history_text: Callable[[], str]
    safe_artifact_name: Callable[[str], str]
    diff_artifact_targets: Callable[[], list[tuple[str, str]]]


def static_context_file_specs(helpers: ContextRenderHelpers) -> tuple[ContextFileSpec, ...]:
    return (
        ContextFileSpec(
            rel="context/task.md",
            section="Task",
            title="Task",
            description="original task and current run state.",
            render=render_task,
        ),
        ContextFileSpec(
            rel="context/current_status.md",
            section="Current Repo State",
            title="Current Status",
            description="latest git status and diff stat.",
            render=lambda state: helpers.repo_status_text(),
        ),
        ContextFileSpec(
            rel="context/current_diff.patch",
            section="Current Repo State",
            title="Current Diff",
            description="latest git diff patch.",
            render=lambda state: helpers.repo_diff_text(),
        ),
        ContextFileSpec(
            rel="context/environment.md",
            section="Current Repo State",
            title="Environment",
            description="cwd, shell, workspace, approvals, and sandbox metadata.",
            render=render_environment_context,
        ),
        ContextFileSpec(
            rel="context/current_diff.md",
            section="Current Repo State",
            title="Current Repo State",
            description="latest git status and diff in Markdown form.",
            render=lambda state: render_repo_state(state, helpers),
            include_in_index=False,
        ),
        ContextFileSpec(
            rel="context/last_failure.md",
            section="Recent Failures",
            title="Last Failure",
            description="latest failing tool result, if any.",
            render=lambda state: render_last_failure(state, helpers),
        ),
        ContextFileSpec(
            rel="context/observations.md",
            section="Recovery",
            title="Observations",
            description="typed observations from tool results and harness events.",
            render=lambda state: render_observations(state, helpers),
        ),
        ContextFileSpec(
            rel="context/transcript.md",
            section="Recovery",
            title="Transcript",
            description="model and tool call/result pairing.",
            render=lambda state: render_transcript(state, helpers),
        ),
        ContextFileSpec(
            rel="context/history/compacted.md",
            section="History",
            title="Compacted History",
            description="latest compacted checkpoint summary, if any.",
            render=lambda state: render_compacted_history(state, helpers),
        ),
        ContextFileSpec(
            rel="context/history/summary.md",
            section="History",
            title="History Summary",
            description="latest compacted recovery summary.",
            render=lambda state: render_compacted_history(state, helpers),
        ),
        ContextFileSpec(
            rel="context/history/raw.jsonl",
            section="History",
            title="Raw History",
            description="durable event log snapshot copied under ContextFS.",
            render=lambda state: helpers.raw_history_text(),
        ),
    )


def render_task(state: "RunState") -> str:
    return "\n".join(
        [
            "# Task",
            "",
            state.task,
            "",
            f"run_id: {state.run_id}",
            f"status: {state.status}",
            f"turn_count: {state.turn_count}",
            f"tool_call_count: {state.tool_call_count}",
            "",
        ]
    )


def render_repo_state(state: "RunState", helpers: ContextRenderHelpers) -> str:
    del state
    return "\n".join(
        [
            "# Current Repo State",
            "",
            helpers.repo_status_text(),
            "",
            "## Current Diff",
            "",
            "```diff",
            helpers.repo_diff_text().strip(),
            "```",
            "",
        ]
    )


def render_last_failure(state: "RunState", helpers: ContextRenderHelpers) -> str:
    for step in reversed(state.tool_steps):
        if step.result.ok:
            continue
        artifacts = _safe_tool_artifacts(step, helpers)
        readable_artifacts = ", ".join(helpers.context_ref(artifact) for artifact in artifacts) or "(none)"
        return "\n".join(
            [
                "# Last Failure",
                "",
                f"tool: {step.call.name}",
                f"call_id: {step.call.id}",
                f"failure_kind: {step.result.failure_kind or step.result.data.get('failure_kind') or 'unknown'}",
                f"artifact: {readable_artifacts}",
                "",
                "## Preview",
                "",
                "```text",
                step.result.content_preview or step.result.output,
                "```",
                "",
            ]
        )
    return "# Last Failure\n\nNo failing tool result yet.\n"


def render_compacted_history(state: "RunState", helpers: ContextRenderHelpers) -> str:
    if state.context_checkpoint.strip():
        artifact = f"\n\nCheckpoint artifact: {state.context_checkpoint_artifact}" if state.context_checkpoint_artifact else ""
        return f"# Compacted History\n\n{helpers.sanitize_value(state.context_checkpoint).strip()}{helpers.sanitize_value(artifact)}\n"
    return "# Compacted History\n\nNo compaction checkpoint yet.\n"


def render_observations(state: "RunState", helpers: ContextRenderHelpers) -> str:
    lines = ["# Observations", ""]
    if not state.observations:
        lines.append("No observations recorded yet.")
    for observation in state.observations:
        refs = helpers.safe_transcript_refs(observation.refs)
        data = json.dumps(helpers.sanitize_data(observation.data), sort_keys=True) if observation.data else "{}"
        subject = helpers.sanitize_value(observation.subject)
        lines.extend(
            [
                f"## {observation.kind}: {subject}",
                "",
                helpers.sanitize_value(observation.summary),
                "",
                f"refs: {refs}",
                f"data: `{data}`",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def render_transcript(state: "RunState", helpers: ContextRenderHelpers) -> str:
    lines = ["# Transcript", ""]
    if not state.transcript.items:
        lines.append("No transcript items recorded yet.")
    for item in state.transcript.items:
        refs = helpers.safe_transcript_refs(item.artifact_refs)
        data = json.dumps(helpers.sanitize_data(item.data), sort_keys=True) if item.data else "{}"
        lines.extend(
            [
                f"## {item.kind}: {item.id}",
                "",
                f"turn_id: {item.turn_id or ''}",
                f"model_call_id: {item.model_call_id or ''}",
                f"tool_call_id: {item.tool_call_id or ''}",
                f"tool_name: {item.tool_name or ''}",
                f"summary: {helpers.sanitize_value(item.summary)}",
                f"refs: {refs}",
                f"data: `{data}`",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def render_tool_docs(state: "RunState", helpers: ContextRenderHelpers) -> tuple[RenderedContextFile, ...]:
    files: list[RenderedContextFile] = []
    lines = ["# Tool Context", ""]
    by_tool: dict[str, list[str]] = {}
    for step in state.tool_steps:
        artifacts = _safe_tool_artifacts(step, helpers)
        if not artifacts:
            continue
        entries = by_tool.setdefault(step.call.name, [])
        for artifact in artifacts:
            readable = helpers.context_ref(artifact)
            entries.append(f"- {readable}: `{step.call.id}` {'ok' if step.result.ok else 'failed'}")
    tool_names = list(TOOL_CONTEXT_DESCRIPTIONS)
    tool_names.extend(sorted(tool_name for tool_name in by_tool if tool_name not in TOOL_CONTEXT_DESCRIPTIONS))
    for tool_name in tool_names:
        description = TOOL_CONTEXT_DESCRIPTIONS.get(tool_name, "Tool outputs captured during this run.")
        safe_name = helpers.safe_artifact_name(tool_name)
        entries = by_tool.get(tool_name, ["- No readable output artifacts yet."])
        tool_doc = "# Tool Output: " + tool_name + "\n\n" + description + "\n\n" + "\n".join(entries) + "\n"
        files.append(RenderedContextFile(rel=f"context/tools/{safe_name}.md", content=tool_doc))
        lines.append(f"- {helpers.context_ref(f'context/tools/{safe_name}.md')}")
    files.append(RenderedContextFile(rel="context/tools/INDEX.md", content="\n".join(lines) + "\n"))
    return tuple(files)


def render_diff_docs(state: "RunState", helpers: ContextRenderHelpers) -> tuple[RenderedContextFile, ...]:
    files: list[RenderedContextFile] = []
    lines = ["# ContextFS Diffs", "", f"- {helpers.context_ref('context/current_diff.patch')}: latest aggregate workspace diff."]
    seen: set[str] = set()
    for artifact, target in helpers.diff_artifact_targets():
        if not artifact or artifact in seen:
            continue
        seen.add(artifact)
        source = state.output_dir / artifact
        if not source.exists():
            continue
        files.append(RenderedContextFile(rel=target, content=source.read_text(errors="replace")))
        lines.append(f"- {helpers.context_ref(target)}: copied from `{artifact}`.")
    files.append(RenderedContextFile(rel="context/diffs/INDEX.md", content="\n".join(lines) + "\n"))
    return tuple(files)


def render_context_index(
    state: "RunState",
    entries: Sequence[ContextIndexEntry],
    helpers: ContextRenderHelpers,
) -> str:
    by_section: dict[str, list[ContextIndexEntry]] = {}
    for entry in entries:
        by_section.setdefault(entry.section, []).append(entry)

    lines = [
        "# tinyagent ContextFS",
        "",
        "Read only what is needed. Large outputs are stored here to keep prompt context bounded.",
        "",
    ]
    for section in ("Task", "Current Repo State", "Recent Failures", "Recovery"):
        section_entries = by_section.get(section, [])
        if not section_entries:
            continue
        lines.append(f"## {section}")
        for entry in section_entries:
            lines.append(f"- {helpers.context_ref(entry.path)}: {entry.description}")
            if entry.read_hint:
                lines.append(f"  Suggested read: `{entry.read_hint}`")
        lines.append("")

    lines.append("## Tool Outputs")
    if not state.tool_steps:
        lines.append("- No tool outputs yet.")
    else:
        for step in state.tool_steps:
            artifacts = _safe_tool_artifacts(step, helpers)
            ok = "ok" if step.result.ok else "failed"
            if artifacts:
                for artifact in artifacts:
                    readable = helpers.context_ref(artifact)
                    lines.append(f"- {readable}: {step.call.name} `{step.call.id}` {ok}. Artifact id: `{artifact}`.")
                    lines.append(f'  Suggested read: `context_read({{"ref":"contextfs:{readable}"}})`')
            else:
                lines.append(f"- {step.call.name} `{step.call.id}` {ok}: no artifact.")

    history_entries = by_section.get("History", [])
    lines.extend(["", "## History"])
    for entry in history_entries:
        lines.append(f"- {helpers.context_ref(entry.path)}: {entry.description}")
        if entry.read_hint:
            lines.append(f"  Suggested read: `{entry.read_hint}`")
    lines.append("")
    return "\n".join(lines)


def _safe_tool_artifacts(step: "ToolStep", helpers: ContextRenderHelpers) -> tuple[str, ...]:
    refs = (helpers.safe_recovery_artifact_ref(ref) for ref in helpers.tool_artifact_refs(step))
    return tuple(dict.fromkeys(ref for ref in refs if ref))
