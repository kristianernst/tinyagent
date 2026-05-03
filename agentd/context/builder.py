"""Model-visible context rendering."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

from agentd.context.checkpoint import artifact_refs_from_tool_steps, is_test_command_text
from agentd.context.instructions import load_project_instructions
from agentd.context.types import BuiltContext, ContextConfig, ContextExclusion, ContextItem, ProjectInstructions
from agentd.contracts import Tool
from agentd.events import json_safe
from agentd.state import Message, RunState, ToolStep

DEFAULT_SHELL_PREFLIGHT_COMMANDS = ("rg", "git", "python3", "python", "sed")


class ContextBuilder:
    def __init__(self, *, system_prompt: str, config: ContextConfig | None = None) -> None:
        self.system_prompt = system_prompt
        self.config = config or ContextConfig()

    def build(self, state: RunState) -> BuiltContext:
        project_instructions = load_project_instructions(state.workspace.root, self.config)
        environment = render_environment_context(state, self.config)
        project = render_project_instructions(project_instructions)
        task = f"Task:\n{state.task}"
        finish_gate = render_finish_gate_messages(state)
        contextfs_index_path, contextfs_index = render_contextfs_index(state)
        checkpoint = render_context_checkpoint(state)
        recent_tools = render_recent_tool_steps(state, self.config)
        candidates = [
            _item("system:profile", "system", self.system_prompt, "system_prompt", 1000, stable=True),
            _item("environment:current", "user", environment, "environment", 850, stable=True),
            _item("project:instructions", "user", project, "project_instructions", 800, stable=True),
            _item("task:current", "user", task, "task", 950, stable=True),
            _item("contextfs:index", "user", contextfs_index, "contextfs_index", 900, stable=True)
            if contextfs_index
            else None,
            _item("finish_gate:messages", "user", finish_gate, "finish_gate", 780) if finish_gate else None,
            _item("working_state:checkpoint", "user", checkpoint, "working_state", 700, stable=True),
            _item("recent_tools:preview", "user", recent_tools, "recent_tool_steps", 600, stable=True),
        ]
        included, excluded = _pack_items([item for item in candidates if item is not None], self.config)
        messages = [
            Message(role=item.role, content=item.text, meta={"context_layer": item.source, "context_item_id": item.id})
            for item in included
        ]
        static_context_chars = sum(len(message_text(message)) for message in messages if message.meta.get("context_layer") != "recent_tool_steps")
        tool_context_chars = len(recent_tools)
        return BuiltContext(
            messages=messages,
            token_estimate=estimate_messages_tokens(messages),
            static_context_chars=static_context_chars,
            tool_context_chars=tool_context_chars,
            project_instruction_chars=project_instructions.chars,
            artifacts=artifact_refs_from_tool_steps(_tool_steps_since_checkpoint(state)),
            included=included,
            excluded=excluded,
            contextfs_index_path=contextfs_index_path,
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


def render_environment_context(state: RunState, config: ContextConfig | None = None) -> str:
    config = config or ContextConfig()
    shell = config.shell or os.environ.get("SHELL") or "/bin/sh"
    preflight = state.shell_preflight or {}
    commands = preflight.get("commands") if isinstance(preflight.get("commands"), dict) else {}
    envelope = state.workspace_envelope
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
            f"  workspace_mode: {envelope.mode if envelope else 'current'}",
            f"  workspace_effective_mode: {envelope.effective_mode if envelope else 'current'}",
            f"  approval_mode: {state.approval_mode}",
            f"  sandbox_mode: {envelope.sandbox_mode if envelope else 'none'}",
            f"  sandbox_enforced: {bool(envelope.sandbox_enforced) if envelope else False}",
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


def render_contextfs_index(state: RunState) -> tuple[str | None, str]:
    relative = "context/INDEX.md"
    path = state.output_dir / relative
    if not path.exists():
        return None, ""
    return relative, "\n".join(["ContextFS index:", "", path.read_text()])


def render_finish_gate_messages(state: RunState) -> str:
    if not state.finish_gate_messages:
        return ""
    lines = ["Finish gate feedback:"]
    lines.extend(f"- {message}" for message in state.finish_gate_messages[-5:])
    return "\n".join(lines)


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


def _is_diff_or_status_step(step: ToolStep) -> bool:
    if step.call.name != "shell":
        return False
    cmd = str(step.call.args.get("cmd", "")).lower()
    return any(pattern in cmd for pattern in ("git status", "git diff", "git show", "git log"))


def _is_test_step(step: ToolStep) -> bool:
    return step.call.name == "shell" and is_test_command_text(str(step.call.args.get("cmd", "")))


def _small_json(value: object, *, max_chars: int = 2_000) -> str:
    encoded = json.dumps(json_safe(value), sort_keys=True)
    if len(encoded) <= max_chars:
        return encoded
    return json.dumps({"_truncated": True, "json_chars": len(encoded), "preview": encoded[:max_chars]}, sort_keys=True)


def _item(
    item_id: str,
    role: str,
    text: str,
    source: str,
    priority: int,
    *,
    stable: bool = False,
) -> ContextItem:
    return ContextItem(
        id=item_id,
        role=role,
        text=text,
        source=source,
        priority=priority,
        token_estimate=estimate_tokens(text),
        stable=stable,
    )


def _pack_items(items: Sequence[ContextItem], config: ContextConfig) -> tuple[list[ContextItem], list[ContextExclusion]]:
    budget = config.effective_compact_at_tokens
    included: list[ContextItem] = []
    excluded: list[ContextExclusion] = []
    total = 0
    for item in sorted(items, key=lambda value: (-value.priority, value.id)):
        if item.stable or total + item.token_estimate <= budget:
            included.append(item)
            total += item.token_estimate
        else:
            excluded.append(ContextExclusion(item_id=item.id, reason="budget", token_estimate=item.token_estimate))
    return sorted(included, key=lambda value: items.index(value)), excluded


def _tool_dict(tool: Tool) -> dict[str, Any]:
    return {"name": tool.name, "schema": dict(tool.schema)}
