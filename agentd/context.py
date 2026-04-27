"""Model-visible context construction and local compaction."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentd.contracts import Tool
from agentd.events import json_safe
from agentd.output import write_text_artifact
from agentd.state import Message, RunState, ToolStep

PROJECT_INSTRUCTION_FILE = "AGENTS.md"
DEFAULT_SHELL_PREFLIGHT_COMMANDS = ("rg", "git", "python3", "python", "sed")


@dataclass(frozen=True)
class ContextConfig:
    project_instruction_max_chars: int = 32 * 1024
    max_recent_tool_tokens: int = 12_000
    compact_after_tool_steps: int = 16
    model_context_window: int = 128_000
    compact_at_tokens: int = 96_000
    reserve_output_tokens: int = 8_000
    shell: str | None = None

    @property
    def effective_compact_at_tokens(self) -> int:
        return min(self.compact_at_tokens, max(1, self.model_context_window - self.reserve_output_tokens))


@dataclass(frozen=True)
class ArtifactRef:
    path: str
    description: str = ""


@dataclass
class ContextState:
    objective: str = ""
    constraints: list[str] = field(default_factory=list)
    files_seen: dict[str, str] = field(default_factory=dict)
    files_changed: dict[str, str] = field(default_factory=dict)
    commands_run: list[str] = field(default_factory=list)
    tests_run: list[str] = field(default_factory=list)
    known_facts: list[str] = field(default_factory=list)
    open_issues: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    artifacts: list[ArtifactRef] = field(default_factory=list)
    compaction_count: int = 0


@dataclass(frozen=True)
class ProjectInstructions:
    content: str = ""
    files: tuple[str, ...] = ()
    truncated: bool = False

    @property
    def chars(self) -> int:
        return len(self.content)


@dataclass(frozen=True)
class BuiltContext:
    messages: list[Message]
    token_estimate: int
    static_context_chars: int
    tool_context_chars: int
    project_instruction_chars: int
    artifacts: list[ArtifactRef] = field(default_factory=list)


class ContextBuilder:
    def __init__(self, *, system_prompt: str, config: ContextConfig | None = None) -> None:
        self.system_prompt = system_prompt
        self.config = config or ContextConfig()

    def build(self, state: RunState) -> BuiltContext:
        project_instructions = load_project_instructions(state.workspace.root, self.config)
        environment = render_environment_context(state, self.config)
        project = render_project_instructions(project_instructions)
        task = f"Task:\n{state.task}"
        checkpoint = render_context_checkpoint(state)
        recent_tools = render_recent_tool_steps(state, self.config)
        messages = [
            Message(role="system", content=self.system_prompt),
            Message(role="user", content=environment, meta={"context_layer": "environment"}),
            Message(role="user", content=project, meta={"context_layer": "project_instructions"}),
            Message(role="user", content=task, meta={"context_layer": "task"}),
            Message(role="user", content=checkpoint, meta={"context_layer": "working_state"}),
            Message(role="user", content=recent_tools, meta={"context_layer": "recent_tool_steps"}),
        ]
        static_context_chars = sum(len(message_text(message)) for message in messages[:-1])
        tool_context_chars = len(recent_tools)
        return BuiltContext(
            messages=messages,
            token_estimate=estimate_messages_tokens(messages),
            static_context_chars=static_context_chars,
            tool_context_chars=tool_context_chars,
            project_instruction_chars=project_instructions.chars,
            artifacts=artifact_refs_from_tool_steps(_tool_steps_since_checkpoint(state)),
        )


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def estimate_messages_tokens(messages: Sequence[Message]) -> int:
    return sum(estimate_tokens(message_text(message)) for message in messages)


def estimate_tools_tokens(tools: Sequence[Tool]) -> int:
    return sum(estimate_tokens(json.dumps(_tool_dict(tool), sort_keys=True)) for tool in tools)


def message_text(message: Message) -> str:
    if isinstance(message.content, str):
        return message.content
    return json.dumps(json_safe(message.content), sort_keys=True)


def load_project_instructions(workspace_root: Path, config: ContextConfig | None = None) -> ProjectInstructions:
    config = config or ContextConfig()
    paths = _instruction_paths(workspace_root)
    chunks: list[str] = []
    files: list[str] = []
    remaining = max(config.project_instruction_max_chars, 0)
    truncated = False

    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        chunk = f"## {path}\n\n{text.strip()}\n"
        files.append(str(path))
        if remaining <= 0:
            truncated = True
            continue
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining].rstrip())
            truncated = True
            remaining = 0
            continue
        chunks.append(chunk.rstrip())
        remaining -= len(chunk)

    return ProjectInstructions(content="\n\n".join(chunks), files=tuple(files), truncated=truncated)


def render_environment_context(state: RunState, config: ContextConfig | None = None) -> str:
    config = config or ContextConfig()
    shell = config.shell or os.environ.get("SHELL") or "/bin/sh"
    preflight = state.shell_preflight or {}
    commands = preflight.get("commands") if isinstance(preflight.get("commands"), dict) else {}
    command_lines = [
        f"    {name}: {bool(commands.get(name, False))}" for name in sorted(set(DEFAULT_SHELL_PREFLIGHT_COMMANDS) | set(commands))
    ]
    return "\n".join(
        [
            "<environment_context>",
            f"  cwd: {state.workspace.root}",
            f"  shell: {shell}",
            "  shell_preflight:",
            *command_lines,
            f"    python_available: {bool(preflight.get('python_available', False))}",
            "  sandbox_mode: none",
            "  shell_env: sanitized",
            f"  writable_root: {state.workspace.root}",
            "</environment_context>",
        ]
    )


def render_project_instructions(instructions: ProjectInstructions) -> str:
    if not instructions.content:
        return "Project instructions:\nNo AGENTS.md instructions discovered."
    files = "\n".join(f"- {path}" for path in instructions.files)
    truncated = "\n\n[project instructions truncated at configured character cap]" if instructions.truncated else ""
    return "\n".join(
        [
            "Project instructions (AGENTS.md, root-to-leaf):",
            files,
            "",
            "<project_instructions>",
            instructions.content,
            f"</project_instructions>{truncated}",
        ]
    )


def render_context_checkpoint(state: RunState) -> str:
    checkpoint = state.context_checkpoint.strip()
    if checkpoint:
        artifact = f"\n\nCheckpoint artifact: {state.context_checkpoint_artifact}" if state.context_checkpoint_artifact else ""
        return f"Previous checkpoint:\n{checkpoint}{artifact}"
    return "Previous checkpoint:\nNo checkpoint yet."


def render_recent_tool_steps(state: RunState, config: ContextConfig | None = None) -> str:
    config = config or ContextConfig()
    steps = _tool_steps_since_checkpoint(state)
    if not steps:
        label = "None since the last checkpoint." if state.context_checkpoint else "None yet."
        return f"Recent tool results:\n{label}"

    rendered = [_render_tool_step(step, state) for step in steps]
    selected_indexes = _select_recent_tool_indexes(steps, rendered, config)
    sections = ["Recent tool results after latest checkpoint:" if state.context_checkpoint else "Recent tool results:"]
    for index in selected_indexes:
        sections.append(rendered[index])
    return "\n\n".join(sections)


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


def _instruction_paths(workspace_root: Path) -> list[Path]:
    root = workspace_root.expanduser().resolve()
    paths = [Path.home() / ".tinyagent" / PROJECT_INSTRUCTION_FILE]
    git_root = _git_root(root) or root
    try:
        relative = root.relative_to(git_root)
    except ValueError:
        git_root = root
        relative = Path()
    current = git_root
    paths.append(current / PROJECT_INSTRUCTION_FILE)
    for part in relative.parts:
        current = current / part
        paths.append(current / PROJECT_INSTRUCTION_FILE)
    return _dedupe_paths(paths)


def _git_root(root: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return Path(value).resolve() if value else None


def _dedupe_paths(paths: Sequence[Path]) -> list[Path]:
    output: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        output.append(resolved)
    return output


def _tool_steps_since_checkpoint(state: RunState) -> list[ToolStep]:
    return state.tool_steps[state.context_checkpoint_tool_step_count :]


def _select_recent_tool_indexes(steps: Sequence[ToolStep], rendered: Sequence[str], config: ContextConfig) -> list[int]:
    mandatory = {
        len(steps) - 1,
        _latest_index(steps, lambda step: not step.result.ok),
        _latest_index(steps, _is_diff_or_status_step),
        _latest_index(steps, lambda step: step.call.name == "apply_patch"),
        _latest_index(steps, _is_test_step),
    }
    selected = {index for index in mandatory if index is not None and index >= 0}
    token_count = sum(estimate_tokens(rendered[index]) for index in selected)
    budget = max(config.max_recent_tool_tokens, 0)

    for index in range(len(steps) - 1, -1, -1):
        if index in selected:
            continue
        next_tokens = estimate_tokens(rendered[index])
        if token_count + next_tokens <= budget:
            selected.add(index)
            token_count += next_tokens
    return sorted(selected)


def _latest_index(steps: Sequence[ToolStep], predicate: Any) -> int | None:
    for index in range(len(steps) - 1, -1, -1):
        if predicate(steps[index]):
            return index
    return None


def _render_tool_step(step: ToolStep, state: RunState) -> str:
    call = step.call
    result = step.result
    limit = state.budgets.max_command_output_chars_visible
    output = result.output[:limit]
    suffix = "\n[truncated]" if len(result.output) > limit else ""
    return "\n".join(
        [
            f"Tool: {call.name}",
            f"Call ID: {call.id}",
            f"Args: {_small_json(call.args)}",
            f"OK: {result.ok}",
            f"Data: {_small_json(result.data)}",
            "Output:",
            f"{output}{suffix}",
        ]
    )


def _collect_event_context(state: RunState, context_state: ContextState) -> None:
    commands: list[str] = []
    tests: list[str] = []
    for event in state.events:
        data = event.data
        if event.type == "FileRead":
            path = str(data.get("path", ""))
            if path:
                context_state.files_seen[path] = f"read {data.get('line_count', 0)} line(s)"
        elif event.type == "SearchCompleted":
            path = str(data.get("path", "."))
            query = str(data.get("query", ""))
            context_state.files_seen[path] = f"searched for {query!r}"
        elif event.type == "PatchApplied":
            for path in data.get("paths", []):
                context_state.files_changed[str(path)] = "changed by apply_patch"
        elif event.type == "CommandFinished":
            command = str(data.get("cmd", ""))
            if not command:
                continue
            outcome = _command_outcome(data)
            commands.append(f"{command} -> {outcome}")
            if _is_test_command_text(command):
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


def _is_diff_or_status_step(step: ToolStep) -> bool:
    if step.call.name != "shell":
        return False
    cmd = str(step.call.args.get("cmd", "")).lower()
    return any(pattern in cmd for pattern in ("git status", "git diff", "git show", "git log"))


def _is_test_step(step: ToolStep) -> bool:
    return step.call.name == "shell" and _is_test_command_text(str(step.call.args.get("cmd", "")))


def _is_test_command_text(command: str) -> bool:
    return bool(
        re.search(
            r"(^|[;&|]\s*)((uv\s+run\s+)?pytest|python\s+-m\s+pytest|python\s+-m\s+unittest|npm\s+test|pnpm\s+test|yarn\s+test|cargo\s+test|go\s+test)\b",
            command,
        )
    )


def _artifact_description(step: ToolStep) -> str:
    if step.call.name == "shell":
        cmd = str(step.call.args.get("cmd", ""))
        return f"shell output for {cmd[:120]}"
    if step.call.name == "apply_patch":
        paths = step.result.data.get("paths", [])
        return f"apply_patch output for {', '.join(str(path) for path in paths)}"
    return f"{step.call.name} output"


def _small_json(value: object, *, max_chars: int = 2_000) -> str:
    encoded = json.dumps(json_safe(value), sort_keys=True)
    if len(encoded) <= max_chars:
        return encoded
    return json.dumps({"_truncated": True, "json_chars": len(encoded), "preview": encoded[:max_chars]}, sort_keys=True)


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


def _tool_dict(tool: Tool) -> dict[str, Any]:
    return {"name": tool.name, "schema": dict(tool.schema)}
