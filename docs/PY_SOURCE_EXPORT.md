wrote docs/PY_SOURCE_EXPORT.md with 26 Python files
_py_markdown.py`.

## `agentctl/__init__.py`

```python
"""Command-line package for tinyagent."""
```

## `agentctl/cli.py`

```python
"""CLI entrypoint for tinyagent."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from agentd import __version__
from agentd.events import ConsoleTextSink, JsonlStreamSink
from agentd.kernel import Kernel
from agentd.models import FakeModelProvider, ProviderError
from agentd.policy import default_policy
from agentd.profiles import ApexCoderProfile
from agentd.providers.openai_compat import OpenAICompatibleProvider
from agentd.replay import replay_run
from agentd.state import ModelResponse, ToolCall
from agentd.tools import default_tools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentctl",
        description="Control the tinyagent harness.",
    )
    parser.add_argument("--version", action="version", version=f"agentctl {__version__}")

    subparsers = parser.add_subparsers(dest="command")
    run_parser = subparsers.add_parser("run", help="Run an agent task.")
    run_parser.add_argument("task", help="Task for the agent.")
    run_parser.add_argument("--provider", choices=["fake", "openai-compatible"], default="fake")
    run_parser.add_argument("--workspace", default=".")
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--output-dir", type=Path)
    run_parser.add_argument(
        "--stream",
        choices=["off", "text", "jsonl"],
        default="off",
        help="Stream model progress live while preserving the run trace.",
    )

    replay_parser = subparsers.add_parser("replay", help="Replay a recorded agent run.")
    replay_parser.add_argument("run_path", type=Path, help="Run directory or events.jsonl path.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "run":
        try:
            model = _model_for(args.provider, args.task)
        except ProviderError as exc:
            print(f"provider error: {exc}")
            return 1
        kernel = Kernel(
            model=model,
            profile=ApexCoderProfile(),
            tools=default_tools(),
            policy=default_policy(),
            stream=args.stream != "off",
            event_sink=_stream_sink(args.stream),
        )
        state = kernel.run(args.task, workspace=args.workspace, run_id=args.run_id, output_dir=args.output_dir)
        if args.stream == "jsonl":
            return 1 if state.failed else 0
        if args.stream == "text" and state.final_output:
            print()
        print(f"run_id: {state.run_id}")
        print(f"output_dir: {state.output_dir}")
        print(f"status: {'failed' if state.failed else 'completed'}")
        if state.failed:
            print(f"failure: {state.failure_reason}")
            return 1
        if state.final_output and args.stream != "text":
            print(state.final_output)
        return 0

    if args.command == "replay":
        print(replay_run(args.run_path), end="")
        return 0

    parser.error(f"unknown command '{args.command}'")
    return 2


def _model_for(provider: str, task: str):
    if provider == "fake":
        return FakeModelProvider(_fake_responses(task))
    if provider == "openai-compatible":
        return OpenAICompatibleProvider.from_env()
    raise ValueError(f"Unknown provider: {provider}")


def _stream_sink(mode: str):
    if mode == "text":
        return ConsoleTextSink(sys.stdout)
    if mode == "jsonl":
        return JsonlStreamSink(sys.stdout)
    return None


def _fake_responses(task: str) -> list[ModelResponse]:
    path = _first_mentioned_file(task)
    if path is None:
        return [ModelResponse(content="Fake run finished.", finish_reason="stop")]
    return [
        ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"sed -n '1,120p' {path}"}),)),
        ModelResponse(content=f"Fake run finished after reading {path}.", finish_reason="stop"),
    ]


def _first_mentioned_file(task: str) -> str | None:
    match = re.search(r"(?P<path>[\w./-]+\.[A-Za-z0-9_+-]+)", task)
    return match.group("path") if match else None


if __name__ == "__main__":
    raise SystemExit(main())
```

## `agentd/__init__.py`

```python
"""Core runtime package for tinyagent."""

__all__ = ["__version__"]

__version__ = "0.1.0"
```

## `agentd/context/__init__.py`

```python
"""Context construction and deterministic compaction."""

from agentd.context.builder import (
    ContextBuilder,
    estimate_messages_tokens,
    estimate_tokens,
    estimate_tools_tokens,
    message_text,
    render_context_checkpoint,
    render_environment_context,
    render_project_instructions,
    render_recent_tool_steps,
)
from agentd.context.checkpoint import (
    artifact_refs_from_tool_steps,
    compact_state,
    context_state_to_markdown,
    summarize_context_state,
)
from agentd.context.instructions import PROJECT_INSTRUCTION_FILE, load_project_instructions
from agentd.context.types import ArtifactRef, BuiltContext, ContextConfig, ContextState, ProjectInstructions

__all__ = [
    "PROJECT_INSTRUCTION_FILE",
    "ArtifactRef",
    "BuiltContext",
    "ContextBuilder",
    "ContextConfig",
    "ContextState",
    "ProjectInstructions",
    "artifact_refs_from_tool_steps",
    "compact_state",
    "context_state_to_markdown",
    "estimate_messages_tokens",
    "estimate_tokens",
    "estimate_tools_tokens",
    "load_project_instructions",
    "message_text",
    "render_context_checkpoint",
    "render_environment_context",
    "render_project_instructions",
    "render_recent_tool_steps",
    "summarize_context_state",
]
```

## `agentd/context/builder.py`

```python
"""Model-visible context rendering."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from typing import Any

from agentd.context.checkpoint import artifact_refs_from_tool_steps, is_test_command_text
from agentd.context.instructions import load_project_instructions
from agentd.context.types import BuiltContext, ContextConfig, ProjectInstructions
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


def _tool_dict(tool: Tool) -> dict[str, Any]:
    return {"name": tool.name, "schema": dict(tool.schema)}
```

## `agentd/context/checkpoint.py`

```python
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
        elif event.type == "command.completed":
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
```

## `agentd/context/instructions.py`

```python
"""Project instruction loading for model-visible context."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from agentd.context.types import ContextConfig, ProjectInstructions

PROJECT_INSTRUCTION_FILE = "AGENTS.md"


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
```

## `agentd/context/types.py`

```python
"""Context state and build result types."""

from __future__ import annotations

from dataclasses import dataclass, field

from agentd.state import Message


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
```

## `agentd/contracts.py`

```python
"""Runtime interfaces for models, profiles, tools, policy, and executors."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from agentd.model_stream import ModelDelta
from agentd.state import Message, ModelResponse, PolicyDecision, RunState, ToolCall, ToolResult


class Tool(Protocol):
    """ToolResult.data is small metadata only; large payloads should be artifacts."""

    name: str
    schema: Mapping[str, Any]

    def run(self, call: ToolCall, state: RunState) -> ToolResult: ...


class ModelProvider(Protocol):
    name: str

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse: ...


class StreamingModelProvider(ModelProvider, Protocol):
    def stream(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> Iterable[ModelDelta]: ...


class Profile(Protocol):
    name: str

    def system_prompt(self) -> str: ...

    def build_messages(self, state: RunState) -> Sequence[Message]: ...

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]: ...

    def should_continue(self, state: RunState) -> bool: ...

    def should_finish(self, state: RunState) -> bool: ...

    def should_compact(self, state: RunState) -> bool: ...

    def compact(self, state: RunState) -> None: ...


class PolicyEngine(Protocol):
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision: ...


class Executor(Protocol):
    def run_tool(self, tool: Tool, call: ToolCall, state: RunState) -> ToolResult: ...


class LocalExecutor:
    def run_tool(self, tool: Tool, call: ToolCall, state: RunState) -> ToolResult:
        return tool.run(call, state)
```

## `agentd/events.py`

```python
"""Event records and live sinks emitted by the tinyagent runtime."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, TextIO
from uuid import uuid4

EventVisibility = Literal["internal", "debug", "user", "public"]
EventDurability = Literal["ephemeral", "event_log", "artifact_only"]

DURABLE_EVENT_TYPES = frozenset(
    {
        "run.started",
        "run.completed",
        "run.failed",
        "context.built",
        "compaction.started",
        "checkpoint.completed",
        "model.request.started",
        "model.stream.started",
        "model.completed",
        "model.failed",
        "model.usage",
        "message.completed",
        "tool.call.started",
        "tool.args.completed",
        "tool.policy.evaluated",
        "tool.execution.started",
        "tool.execution.completed",
        "tool.execution.failed",
        "shell.preflight.completed",
        "files.listed",
        "file.read",
        "search.completed",
        "command.started",
        "command.completed",
        "patch.applied",
        "diff.finalized",
        "artifact.created",
    }
)

LIVE_ONLY_EVENT_TYPES = frozenset(
    {
        "model.text.delta",
        "reasoning.summary.delta",
        "reasoning.encrypted",
        "tool.args.delta",
    }
)

EVENT_TYPES = DURABLE_EVENT_TYPES | LIVE_ONLY_EVENT_TYPES


def utc_now() -> datetime:
    return datetime.now(UTC)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return repr(value)


@dataclass(frozen=True)
class Event:
    """Single ordered runtime event.

    Durable and live-only stream events share this envelope. Durability decides
    whether an event is appended to the event log; visibility decides whether a
    sink should present it to users.
    """

    run_id: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    visibility: EventVisibility = "debug"
    durability: EventDurability = "event_log"
    artifact_refs: list[str] = field(default_factory=list)
    turn_id: str | None = None
    item_id: str | None = None
    parent_item_id: str | None = None
    source: str = "tinyagent"
    seq: int = 0
    id: str = field(default_factory=lambda: f"evt_{uuid4().hex}")
    time: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.type not in EVENT_TYPES:
            raise ValueError(f"Unknown event type: {self.type}")
        if self.type in LIVE_ONLY_EVENT_TYPES and self.durability != "ephemeral":
            raise ValueError(f"Live-only event cannot be durable: {self.type}")
        if self.durability == "event_log" and self.type not in DURABLE_EVENT_TYPES:
            raise ValueError(f"Event is not durable: {self.type}")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "seq": self.seq,
            "type": self.type,
            "time": self.time.isoformat().replace("+00:00", "Z"),
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "item_id": self.item_id,
            "parent_item_id": self.parent_item_id,
            "source": self.source,
            "visibility": self.visibility,
            "durability": self.durability,
            "data": json_safe(self.data),
            "artifact_refs": json_safe(self.artifact_refs),
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> Event:
        timestamp = data["time"].replace("Z", "+00:00")
        return cls(
            id=data["id"],
            seq=int(data.get("seq", 0)),
            run_id=data["run_id"],
            type=data["type"],
            time=datetime.fromisoformat(timestamp),
            turn_id=data.get("turn_id"),
            item_id=data.get("item_id"),
            parent_item_id=data.get("parent_item_id"),
            source=data.get("source", "tinyagent"),
            visibility=data.get("visibility", "debug"),
            durability=data.get("durability", "event_log"),
            data=data.get("data", {}),
            artifact_refs=list(data.get("artifact_refs", [])),
        )


def load_events_jsonl(path: Path) -> list[Event]:
    return [Event.from_json_dict(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...


class NullSink:
    def emit(self, event: Event) -> None:
        del event


class ConsoleTextSink:
    def __init__(self, file: TextIO | None = None) -> None:
        self.file = file or sys.stdout

    def emit(self, event: Event) -> None:
        if event.type != "model.text.delta":
            return
        delta = event.data.get("delta")
        if not isinstance(delta, str) or not delta:
            return
        self.file.write(delta)
        self.file.flush()


class JsonlStreamSink:
    def __init__(self, file: TextIO | None = None) -> None:
        self.file = file or sys.stdout

    def emit(self, event: Event) -> None:
        self.file.write(json.dumps(event.to_json_dict(), sort_keys=True) + "\n")
        self.file.flush()


class MemoryEventSink:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


class CompositeSink:
    def __init__(self, *sinks: EventSink) -> None:
        self.sinks = tuple(sinks)

    def emit(self, event: Event) -> None:
        for sink in self.sinks:
            sink.emit(event)
```

## `agentd/kernel.py`

```python
"""Minimal tinyagent kernel loop."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from agentd.context import BuiltContext, estimate_messages_tokens, estimate_tools_tokens, message_text
from agentd.contracts import Executor, LocalExecutor, ModelProvider, PolicyEngine, Profile, Tool
from agentd.events import EventSink, json_safe
from agentd.model_stream import complete_model_call
from agentd.output import (
    capture_final_diff,
    write_model_http_request_artifact,
    write_model_request_artifacts,
    write_model_response_artifact,
    write_run_outputs,
)
from agentd.state import Message, PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult, ToolStep, Workspace
from agentd.tools import shell_preflight

MAX_EVENT_DATA_CHARS = 4_000


class Kernel:
    """Small runtime that owns state, model calls, policy checks, and tool dispatch."""

    def __init__(
        self,
        *,
        model: ModelProvider,
        profile: Profile,
        tools: Iterable[Tool],
        policy: PolicyEngine,
        executor: Executor | None = None,
        budgets: RunBudgets | None = None,
        stream: bool = False,
        event_sink: EventSink | None = None,
    ) -> None:
        self.model = model
        self.profile = profile
        self.tools = {tool.name: tool for tool in tools}
        self.policy = policy
        self.executor = executor or LocalExecutor()
        self.budgets = budgets or RunBudgets()
        self.stream = stream
        self.event_sink = event_sink

    def run(
        self,
        task: str,
        *,
        workspace: Path | str,
        run_id: str | None = None,
        output_dir: Path | None = None,
        stream: bool | None = None,
        event_sink: EventSink | None = None,
    ) -> RunState:
        state = RunState.create(
            task,
            Workspace(Path(workspace)),
            budgets=self.budgets,
            run_id=run_id,
            output_dir=output_dir,
        )
        use_stream = self.stream if stream is None else stream
        state.stream_sink = event_sink if event_sink is not None else self.event_sink
        state.emit(
            "run.started",
            {
                "task": task,
                "workspace_root": str(state.workspace.root),
                "budgets": state.budgets.to_json_dict(),
                "stream": use_stream,
            },
        )
        if "shell" in self.tools:
            state.shell_preflight = shell_preflight()
            state.emit("shell.preflight.completed", state.shell_preflight)

        try:
            self._run_loop(state, stream=use_stream)
        except Exception as exc:  # pragma: no cover - defensive boundary
            state.fail(f"Unhandled exception: {exc}")
        finally:
            self._finalize_message(state)
            capture_final_diff(state)
            self._finalize_run(state)
            write_run_outputs(state)

        return state

    def _run_loop(self, state: RunState, *, stream: bool) -> None:
        while not state.done:
            if self._budget_exhausted(state):
                return
            if not self.profile.should_continue(state):
                state.finish("Run finished by profile.")
                return

            visible_tools = list(self.profile.visible_tools(state, self.tools))
            visible_tool_names = frozenset(tool.name for tool in visible_tools)
            built_context = self._build_context(state, visible_tools)
            if self._should_compact(state):
                self._compact(state)
                built_context = self._build_context(state, visible_tools)
            messages = built_context.messages
            state.emit(
                "context.built",
                {
                    "message_count": len(messages),
                    "visible_tools": [tool.name for tool in visible_tools],
                    "token_estimate": built_context.token_estimate,
                    "static_context_chars": built_context.static_context_chars,
                    "tool_context_chars": built_context.tool_context_chars,
                    "project_instruction_chars": built_context.project_instruction_chars,
                    "context_artifacts": [artifact.path for artifact in built_context.artifacts],
                    "compaction_count": state.compaction_count,
                    "checkpoint_artifact": state.context_checkpoint_artifact or None,
                },
            )
            model_call_index = state.turn_count + 1
            context_artifact, request_artifact = write_model_request_artifacts(
                state,
                call_index=model_call_index,
                provider=self.model.name,
                messages=messages,
                tools=visible_tools,
            )
            http_request_artifact = self._write_provider_payload_artifact(
                state,
                call_index=model_call_index,
                messages=messages,
                tools=visible_tools,
                stream=stream,
            )
            state.emit(
                "model.request.started",
                {
                    "provider": self.model.name,
                    "base_url": _provider_base_url(self.model),
                    "message_count": len(messages),
                    "tool_count": len(visible_tools),
                    "context_artifact": context_artifact,
                    "logical_request_artifact": request_artifact,
                    "http_request_artifact": http_request_artifact,
                },
            )

            try:
                response = complete_model_call(
                    self.model,
                    messages,
                    visible_tools,
                    state,
                    call_index=model_call_index,
                    stream=stream,
                )
            except Exception as exc:
                state.emit("model.failed", {"provider": self.model.name, "reason": str(exc), "turn": model_call_index})
                state.fail(f"Model provider error: {exc}")
                return
            state.turn_count += 1
            response_artifact = write_model_response_artifact(
                state,
                call_index=model_call_index,
                response=response,
            )
            state.emit(
                "model.completed",
                {
                    "provider": self.model.name,
                    "turn": model_call_index,
                    "content_length": len(response.content),
                    "tool_call_count": len(response.tool_calls),
                    "finish_reason": response.finish_reason,
                    "response_artifact": response_artifact,
                    "streamed": bool(response.raw.get("streamed")),
                },
            )

            if not response.tool_calls:
                if response.content:
                    state.finish(response.content)
                else:
                    state.fail("Model returned no content and no tool calls.")
                return

            for call in response.tool_calls:
                if self._tool_budget_exhausted(state):
                    return
                self._dispatch_tool_call(state, call, visible_tool_names=visible_tool_names)
                if state.done:
                    return

            if self.profile.should_finish(state):
                state.finish(response.content or state.final_output or "Run finished by profile.")
                return

    def _dispatch_tool_call(self, state: RunState, call: ToolCall, *, visible_tool_names: frozenset[str]) -> None:
        args_preview = _small_event_data(call.args)
        state.emit("tool.call.started", {"tool_call_id": call.id, "tool": call.name})
        state.emit(
            "tool.args.completed",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "args": args_preview,
                "args_preview": args_preview,
            },
        )
        state.tool_call_count += 1

        tool = self.tools.get(call.name)
        if tool is None:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=f"Unknown tool requested: {call.name}",
                ok=False,
                data={"error_type": "UnknownTool", "available_tools": sorted(self.tools)},
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            return

        if call.name not in visible_tool_names:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=f"Tool is not visible for this profile: {call.name}",
                ok=False,
                data={"blocked": True, "error_type": "ToolNotVisible", "visible_tools": sorted(visible_tool_names)},
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            return

        try:
            decision = self.policy.evaluate(call, state)
        except Exception as exc:
            decision = PolicyDecision.deny(f"Policy engine error: {exc}")
            self._record_policy_decision(state, call, decision)
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=decision.reason,
                ok=False,
                data={"blocked": True, "error_type": type(exc).__name__},
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            state.fail(decision.reason)
            return

        self._record_policy_decision(state, call, decision)
        if not decision.allowed:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=decision.reason or "Policy denied tool call.",
                ok=False,
                data={"blocked": True},
            )
            self._append_tool_step(state, call, result)
            self._record_tool_result(state, call, result)
            return

        state.emit("tool.execution.started", {"tool_call_id": call.id, "tool": call.name})
        try:
            result = self.executor.run_tool(tool, call, state)
        except Exception as exc:
            result = ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output=f"Tool error: {exc}",
                ok=False,
                data={"error_type": type(exc).__name__},
            )
        if not result.call_id:
            result = ToolResult(
                tool_name=result.tool_name,
                output=result.output,
                call_id=call.id,
                ok=result.ok,
                data=result.data,
            )
        self._append_tool_step(state, call, result)
        self._record_tool_result(state, call, result)

    def _record_tool_result(self, state: RunState, call: ToolCall, result: ToolResult) -> None:
        output_limit = state.budgets.max_command_output_chars_visible
        output = result.output[:output_limit]
        output_chars = _output_chars(result)
        state.emit(
            "tool.execution.completed" if result.ok else "tool.execution.failed",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "ok": result.ok,
                "blocked": bool(result.data.get("blocked")),
                "output": output,
                "output_chars": output_chars,
                "output_truncated": output_chars > len(output),
                "data": _small_event_data(result.data),
            },
        )

    def _append_tool_step(self, state: RunState, call: ToolCall, result: ToolResult) -> None:
        state.tool_steps.append(ToolStep(call=call, result=result))

    def _record_policy_decision(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> None:
        state.emit(
            "tool.policy.evaluated",
            {
                "tool_call_id": call.id,
                "tool": call.name,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "redacted": decision.redacted,
            },
        )

    def _budget_exhausted(self, state: RunState) -> bool:
        if state.elapsed_seconds() > state.budgets.max_run_seconds:
            state.fail("Run exceeded max_run_seconds budget.")
            return True
        if state.turn_count >= state.budgets.max_turns:
            state.fail("Run exceeded max_turns budget.")
            return True
        if state.tool_call_count >= state.budgets.max_tool_calls:
            state.fail("Run exceeded max_tool_calls budget.")
            return True
        return False

    def _tool_budget_exhausted(self, state: RunState) -> bool:
        if state.tool_call_count >= state.budgets.max_tool_calls:
            state.fail("Run exceeded max_tool_calls budget.")
            return True
        return False

    def _write_provider_payload_artifact(
        self,
        state: RunState,
        *,
        call_index: int,
        messages: list[Message],
        tools: list[Tool],
        stream: bool = False,
    ) -> str | None:
        build_payload = getattr(self.model, "build_stream_payload" if stream else "build_payload", None)
        if not callable(build_payload):
            return None
        payload = build_payload(messages, tools, state)
        if not isinstance(payload, dict):
            return None
        return write_model_http_request_artifact(state, call_index=call_index, payload=payload)

    def _finalize_message(self, state: RunState) -> None:
        if not state.done and not state.failed:
            state.finish("Run finished without explicit final output.")
        if not state.final_output:
            return
        if any(event.type == "message.completed" for event in state.events):
            return
        state.emit(
            "message.completed",
            {
                "role": "assistant",
                "content_chars": len(state.final_output),
                "path": "final.md",
            },
            visibility="user",
            artifact_refs=["final.md"],
        )

    def _finalize_run(self, state: RunState) -> None:
        event_type = "run.failed" if state.failed else "run.completed"
        if any(event.type == event_type for event in state.events):
            return
        data = {
            "status": "failed" if state.failed else "completed",
            "turn_count": state.turn_count,
            "tool_call_count": state.tool_call_count,
            "final_output_chars": len(state.final_output),
            "duration_seconds": state.elapsed_seconds(),
        }
        if state.failed:
            data["reason"] = state.failure_reason or "Unknown failure"
        state.emit(event_type, data)

    def _build_context(self, state: RunState, visible_tools: list[Tool]) -> BuiltContext:
        build_context = getattr(self.profile, "build_context", None)
        if callable(build_context):
            built_context = build_context(state)
        else:
            messages = list(self.profile.build_messages(state))
            built_context = BuiltContext(
                messages=messages,
                token_estimate=estimate_messages_tokens(messages),
                static_context_chars=sum(len(message_text(message)) for message in messages),
                tool_context_chars=0,
                project_instruction_chars=0,
            )
        token_estimate = built_context.token_estimate + estimate_tools_tokens(visible_tools)
        state.context_token_estimate = token_estimate
        return replace(built_context, token_estimate=token_estimate)

    def _should_compact(self, state: RunState) -> bool:
        should_compact = getattr(self.profile, "should_compact", None)
        return callable(should_compact) and bool(should_compact(state))

    def _compact(self, state: RunState) -> None:
        state.emit(
            "compaction.started",
            {
                "profile": self.profile.name,
                "token_estimate": state.context_token_estimate,
                "tool_step_count": len(state.tool_steps),
            },
        )
        self.profile.compact(state)
        state.emit(
            "checkpoint.completed",
            {
                "profile": self.profile.name,
                "compaction_count": state.compaction_count,
                "checkpoint_artifact": state.context_checkpoint_artifact or None,
            },
        )


def _small_event_data(data: dict[str, Any]) -> dict[str, Any]:
    safe = json_safe(data)
    encoded = json.dumps(safe, sort_keys=True)
    if len(encoded) <= MAX_EVENT_DATA_CHARS:
        return safe
    return {
        "_truncated": True,
        "json_chars": len(encoded),
        "preview": encoded[:MAX_EVENT_DATA_CHARS],
    }


def _output_chars(result: ToolResult) -> int:
    value = result.data.get("output_chars")
    return value if isinstance(value, int) else len(result.output)


def _provider_base_url(model: ModelProvider) -> str | None:
    config = getattr(model, "config", None)
    value = getattr(config, "base_url", None)
    return value if isinstance(value, str) else None
```

## `agentd/model_stream.py`

```python
"""Model streaming deltas, assembly, and provider chunk parsing."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from agentd.events import utc_now
from agentd.state import Message, ModelResponse, RunState, ToolCall

ModelDeltaKind = Literal[
    "text_delta",
    "reasoning_summary_delta",
    "reasoning_visible_delta",
    "reasoning_encrypted",
    "tool_call_started",
    "tool_call_args_delta",
    "tool_call_completed",
    "output_item_started",
    "output_item_completed",
    "usage",
    "completed",
    "failed",
]


@dataclass(frozen=True)
class ProviderStreamEvent:
    provider: str
    type: str
    raw: dict[str, Any]
    received_at: str = field(default_factory=lambda: utc_now().isoformat().replace("+00:00", "Z"))


@dataclass(frozen=True)
class ModelDelta:
    kind: ModelDeltaKind
    item_id: str | None = None
    tool_call_id: str | None = None
    delta: str = ""
    data: dict[str, Any] = field(default_factory=dict)


class ModelResponseAssembler:
    def __init__(self, *, provider: str) -> None:
        self.provider = provider
        self.content_parts: list[str] = []
        self.tool_calls: dict[str, _StreamToolCall] = {}
        self.tool_order: list[str] = []
        self.finish_reason: str | None = None
        self.usage: dict[str, Any] = {}

    def accept(self, delta: ModelDelta) -> None:
        match delta.kind:
            case "text_delta":
                self.content_parts.append(delta.delta)
            case "tool_call_started":
                self._tool_call_for(delta)
            case "tool_call_args_delta":
                tool_call = self._tool_call_for(delta)
                tool_call.arguments.append(delta.delta)
            case "tool_call_completed":
                self._tool_call_for(delta).completed = True
            case "usage":
                self.usage.update(delta.data)
            case "completed":
                finish_reason = delta.data.get("finish_reason")
                self.finish_reason = str(finish_reason) if finish_reason is not None else self.finish_reason
            case "failed":
                reason = delta.data.get("reason") or "stream failed"
                raise _provider_error(str(reason))
            case _:
                return

    def response(self) -> ModelResponse:
        raw: dict[str, Any] = {"streamed": True}
        if self.usage:
            raw["usage"] = self.usage
        return ModelResponse(
            content="".join(self.content_parts),
            tool_calls=tuple(self._assembled_tool_call(key) for key in self.tool_order),
            finish_reason=self.finish_reason,
            raw=raw,
        )

    def _tool_call_for(self, delta: ModelDelta) -> _StreamToolCall:
        key = _stream_tool_key(delta)
        if key not in self.tool_calls:
            self.tool_calls[key] = _StreamToolCall()
            self.tool_order.append(key)
        tool_call = self.tool_calls[key]
        if delta.tool_call_id and not delta.tool_call_id.startswith("index_"):
            tool_call.id = delta.tool_call_id
        name = delta.data.get("name")
        if isinstance(name, str) and name:
            tool_call.name = name
        provider_id = delta.data.get("id")
        if isinstance(provider_id, str) and provider_id:
            tool_call.id = provider_id
        return tool_call

    def _assembled_tool_call(self, key: str) -> ToolCall:
        tool_call = self.tool_calls[key]
        if not tool_call.name:
            raise _provider_error("Tool call is missing function.name.")
        raw_arguments = "".join(tool_call.arguments) or "{}"
        try:
            args = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise _provider_error(f"Tool call arguments for {tool_call.name} are invalid JSON.") from exc
        if not isinstance(args, dict):
            raise _provider_error(f"Tool call arguments for {tool_call.name} must be a JSON object.")
        if tool_call.id:
            return ToolCall(id=tool_call.id, name=tool_call.name, args=args)
        return ToolCall(name=tool_call.name, args=args)


@dataclass
class _StreamToolCall:
    id: str = ""
    name: str = ""
    arguments: list[str] = field(default_factory=list)
    completed: bool = False


def complete_model_call(
    model: Any,
    messages: Sequence[Message],
    tools: Sequence[Any],
    state: RunState,
    *,
    stream: bool,
    call_index: int,
) -> ModelResponse:
    if not stream:
        return model.complete(messages, tools, state)
    stream_method = getattr(model, "stream", None)
    if not callable(stream_method):
        return model.complete(messages, tools, state)

    state.emit("model.stream.started", {"provider": model.name, "turn": call_index})
    assembler = ModelResponseAssembler(provider=model.name)
    for delta in stream_method(messages, tools, state):
        _record_model_delta(state, model.name, delta)
        assembler.accept(delta)
    return assembler.response()


def assemble_model_deltas(provider: str, deltas: Iterable[ModelDelta]) -> ModelResponse:
    assembler = ModelResponseAssembler(provider=provider)
    for delta in deltas:
        assembler.accept(delta)
    return assembler.response()


def model_response_to_deltas(response: ModelResponse) -> Iterator[ModelDelta]:
    if response.content:
        yield ModelDelta(kind="text_delta", delta=response.content)
    for call in response.tool_calls:
        yield ModelDelta(
            kind="tool_call_started",
            tool_call_id=call.id,
            data={"id": call.id, "name": call.name, "type": "function"},
        )
        yield ModelDelta(
            kind="tool_call_args_delta",
            tool_call_id=call.id,
            delta=json.dumps(call.args, sort_keys=True),
            data={"id": call.id, "name": call.name},
        )
        yield ModelDelta(
            kind="tool_call_completed",
            tool_call_id=call.id,
            data={"id": call.id, "name": call.name},
        )
    if response.raw.get("usage") and isinstance(response.raw["usage"], dict):
        yield ModelDelta(kind="usage", data=response.raw["usage"])
    yield ModelDelta(kind="completed", data={"finish_reason": response.finish_reason})


def parse_chat_completion(raw: dict[str, Any]) -> ModelResponse:
    try:
        choice = raw["choices"][0]
        message = choice.get("message", {})
    except (KeyError, IndexError, TypeError) as exc:
        raise _provider_error("Model provider response did not include choices[0].message.") from exc

    return ModelResponse(
        content=message.get("content") or "",
        tool_calls=tuple(_parse_tool_call(call) for call in message.get("tool_calls") or []),
        finish_reason=choice.get("finish_reason"),
        raw=raw,
    )


def parse_chat_completion_chunk(raw: dict[str, Any]) -> Iterator[ModelDelta]:
    usage = raw.get("usage")
    if isinstance(usage, dict):
        yield ModelDelta(kind="usage", data=usage)
    for choice in raw.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or {}
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str) and content:
            yield ModelDelta(kind="text_delta", delta=content, data={"provider_chunk_id": raw.get("id")})
        for call in delta.get("tool_calls") or []:
            if isinstance(call, dict):
                yield from _parse_chat_tool_call_delta(call)
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None:
            yield ModelDelta(kind="completed", data={"finish_reason": finish_reason})


def _record_model_delta(state: RunState, provider: str, delta: ModelDelta) -> None:
    match delta.kind:
        case "text_delta":
            state.emit(
                "model.text.delta",
                {"delta": delta.delta, "chars": len(delta.delta), "item_id": delta.item_id},
                visibility="user",
                durability="ephemeral",
                item_id=delta.item_id,
            )
        case "reasoning_summary_delta":
            state.emit(
                "reasoning.summary.delta",
                {"delta": delta.delta, "chars": len(delta.delta)},
                durability="ephemeral",
                item_id=delta.item_id,
            )
        case "reasoning_encrypted":
            state.emit(
                "reasoning.encrypted",
                {"chars": len(delta.delta)},
                visibility="internal",
                durability="ephemeral",
                item_id=delta.item_id,
            )
        case "tool_call_started":
            return
        case "tool_call_args_delta":
            state.emit(
                "tool.args.delta",
                {
                    "tool_call_id": delta.tool_call_id,
                    "tool": delta.data.get("name"),
                    "chars": len(delta.delta),
                    "delta": delta.delta,
                },
                durability="ephemeral",
            )
        case "usage":
            state.emit("model.usage", {"provider": provider, **delta.data})
        case _:
            return


def _parse_chat_tool_call_delta(call: dict[str, Any]) -> Iterator[ModelDelta]:
    function = call.get("function") or {}
    index = call.get("index")
    call_id = call.get("id")
    stream_id = str(call_id) if call_id else f"index_{index}" if index is not None else "index_0"
    data = {
        "index": index,
        "id": call_id,
        "name": function.get("name"),
        "type": call.get("type"),
    }
    if call_id or function.get("name"):
        yield ModelDelta(kind="tool_call_started", tool_call_id=stream_id, data=data)
    arguments = function.get("arguments")
    if isinstance(arguments, str) and arguments:
        yield ModelDelta(kind="tool_call_args_delta", tool_call_id=stream_id, delta=arguments, data=data)


def _parse_tool_call(call: dict[str, Any]) -> ToolCall:
    function = call.get("function") or {}
    name = function.get("name")
    if not name:
        raise _provider_error("Tool call is missing function.name.")
    raw_arguments = function.get("arguments") or "{}"
    try:
        args = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise _provider_error(f"Tool call arguments for {name} are invalid JSON.") from exc
    if not isinstance(args, dict):
        raise _provider_error(f"Tool call arguments for {name} must be a JSON object.")
    call_id = call.get("id")
    if call_id:
        return ToolCall(id=call_id, name=name, args=args)
    return ToolCall(name=name, args=args)


def _stream_tool_key(delta: ModelDelta) -> str:
    index = delta.data.get("index")
    if isinstance(index, int):
        return f"index:{index}"
    if delta.tool_call_id:
        return delta.tool_call_id
    return "index:0"


def _provider_error(message: str):
    from agentd.models import ProviderError

    return ProviderError(message)
```

## `agentd/models.py`

```python
"""Small model provider helpers."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from agentd.contracts import Tool
from agentd.model_stream import ModelDelta, model_response_to_deltas
from agentd.state import Message, ModelResponse, RunState


class ProviderError(RuntimeError):
    """Raised when a model provider cannot produce a response."""


class FakeModelProvider:
    """Deterministic provider for tests and offline harness runs."""

    name = "fake"

    def __init__(self, responses: Sequence[ModelResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        del messages, tools, state
        self.calls += 1
        if not self.responses:
            raise ProviderError("FakeModelProvider has no response left.")
        return self.responses.pop(0)

    def stream(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> Iterator[ModelDelta]:
        response = self.complete(messages, tools, state)
        yield from model_response_to_deltas(response)
```

## `agentd/output.py`

```python
"""Run output writing for tinyagent."""

from __future__ import annotations

import difflib
import json
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agentd.contracts import Tool
from agentd.events import json_safe
from agentd.state import Message, ModelResponse, RunState

ARTIFACTS_DIR = "artifacts"


def write_run_outputs(state: RunState) -> None:
    state.output_dir.mkdir(parents=True, exist_ok=True)

    (state.output_dir / "events.jsonl").write_text(
        "".join(json.dumps(event.to_json_dict(), sort_keys=True) + "\n" for event in state.events),
    )
    (state.output_dir / "final.md").write_text(_final_text(state))
    (state.output_dir / "metrics.json").write_text(json.dumps(_metrics(state), indent=2, sort_keys=True) + "\n")
    (state.output_dir / "final.diff").write_text(state.final_diff)


def capture_final_diff(state: RunState) -> None:
    root = state.workspace.root
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        state.final_diff = ""
        state.emit(
            "diff.finalized",
            {
                "available": False,
                "reason": f"git unavailable: {exc}",
                "path": "final.diff",
                "chars": 0,
            },
        )
        return
    if result.returncode != 0:
        state.final_diff = ""
        state.emit(
            "diff.finalized",
            {
                "available": False,
                "reason": "workspace is not a git worktree",
                "path": "final.diff",
                "chars": 0,
            },
        )
        return

    try:
        diff = subprocess.run(
            _final_diff_command(root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        untracked = _untracked_files(state)
    except (OSError, subprocess.TimeoutExpired) as exc:
        state.final_diff = ""
        state.emit(
            "diff.finalized",
            {
                "available": False,
                "reason": f"git diff failed: {exc}",
                "path": "final.diff",
                "chars": 0,
            },
        )
        return
    untracked_diff = "".join(_new_file_diff(root, path) for path in untracked)
    state.final_diff = _join_diff_parts(diff.stdout, untracked_diff) if diff.returncode == 0 else ""
    state.emit(
        "diff.finalized",
        {
            "available": diff.returncode == 0,
            "reason": "" if diff.returncode == 0 else (diff.stderr.strip() or "git diff failed"),
            "path": "final.diff",
            "chars": len(state.final_diff),
            "untracked_file_count": len(untracked),
        },
    )


def _final_diff_command(root: Path) -> list[str]:
    if _git_has_head(root):
        return ["git", "-C", str(root), "diff", "--no-ext-diff", "HEAD", "--"]
    return ["git", "-C", str(root), "diff", "--no-ext-diff", "--"]


def _git_has_head(root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result.returncode == 0


def write_text_artifact(state: RunState, name: str, content: str, *, kind: str) -> str:
    relative_path = Path(ARTIFACTS_DIR) / name
    artifact_path = state.output_dir / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(content)
    state.emit(
        "artifact.created",
        {
            "kind": kind,
            "path": relative_path.as_posix(),
            "bytes": len(content.encode()),
        },
    )
    return relative_path.as_posix()


def write_json_artifact(state: RunState, name: str, data: dict[str, Any], *, kind: str) -> str:
    return write_text_artifact(
        state,
        name,
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        kind=kind,
    )


def write_model_request_artifacts(
    state: RunState,
    *,
    call_index: int,
    provider: str,
    messages: list[Message],
    tools: list[Tool],
) -> tuple[str, str]:
    context_artifact = write_text_artifact(
        state,
        f"context-{call_index:04d}.md",
        _context_markdown(messages, tools),
        kind="model_context",
    )
    request_artifact = write_json_artifact(
        state,
        f"model-request-logical-{call_index:04d}.json",
        {
            "provider": provider,
            "messages": [_message_dict(message) for message in messages],
            "tools": [_tool_dict(tool) for tool in tools],
        },
        kind="model_request_logical",
    )
    return context_artifact, request_artifact


def write_model_http_request_artifact(
    state: RunState,
    *,
    call_index: int,
    payload: dict[str, Any],
) -> str:
    return write_json_artifact(
        state,
        f"model-request-http-{call_index:04d}.json",
        payload,
        kind="model_request_http",
    )


def write_model_response_artifact(
    state: RunState,
    *,
    call_index: int,
    response: ModelResponse,
) -> str:
    return write_json_artifact(
        state,
        f"model-response-{call_index:04d}.json",
        {
            "content": response.content,
            "finish_reason": response.finish_reason,
            "tool_calls": [_tool_call_dict(call) for call in response.tool_calls],
            "raw": response.raw,
        },
        kind="model_response",
    )


def _final_text(state: RunState) -> str:
    return f"# Final output\n\n{state.final_output or 'No final output produced.'}\n"


def _metrics(state: RunState) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "status": "failed" if state.failed else "completed",
        "failure_reason": state.failure_reason,
        "final_output_chars": len(state.final_output),
        "final_output_path": "final.md",
        "task": state.task,
        "workspace_root": str(state.workspace.root),
        "output_dir": str(state.output_dir),
        "turn_count": state.turn_count,
        "tool_call_count": state.tool_call_count,
        "event_count": state.seq,
        "durable_event_count": len(state.events),
        "duration_seconds": state.elapsed_seconds(),
        "budgets": asdict(state.budgets),
        "final_diff_available": bool(state.final_diff),
        "context_token_estimate": state.context_token_estimate,
        "compaction_count": state.compaction_count,
        "context_checkpoint_artifact": state.context_checkpoint_artifact or None,
        "shell_policy": "best_effort",
        "shell_env": "sanitized",
        "shell_preflight": state.shell_preflight,
        "sandbox_mode": "none",
    }


def _untracked_files(state: RunState) -> list[str]:
    root = state.workspace.root
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [path for path in result.stdout.splitlines() if path and not _excluded_from_final_diff(state, path)]


def _new_file_diff(root: Path, relative_path: str) -> str:
    path = root / relative_path
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    header = f"diff --git a/{relative_path} b/{relative_path}\nnew file mode 100644\nindex 0000000..0000000\n"
    if b"\0" in raw:
        return f"{header}Binary files /dev/null and b/{relative_path} differ\n"
    text = raw.decode(errors="replace")
    lines = text.splitlines()
    body_lines = difflib.unified_diff([], lines, fromfile="/dev/null", tofile=f"b/{relative_path}", lineterm="")
    body = "\n".join(body_lines) + "\n"
    return header + body


def _excluded_from_final_diff(state: RunState, relative_path: str) -> bool:
    if relative_path.startswith(".tinyagent/"):
        return True
    try:
        output_relative = state.output_dir.resolve().relative_to(state.workspace.root).as_posix()
    except ValueError:
        return False
    if output_relative in {"", "."}:
        return True
    return relative_path == output_relative or relative_path.startswith(f"{output_relative}/")


def _join_diff_parts(*parts: str) -> str:
    chunks = [part for part in parts if part]
    if not chunks:
        return ""
    output = chunks[0]
    for chunk in chunks[1:]:
        if output and not output.endswith("\n"):
            output += "\n"
        output += chunk
    return output


def _context_markdown(messages: list[Message], tools: list[Tool]) -> str:
    sections = ["# Model Context\n"]
    sections.append("## Messages\n")
    for message in messages:
        content = message.content if isinstance(message.content, str) else json.dumps(json_safe(message.content), indent=2)
        meta = f"\n```json\n{json.dumps(json_safe(message.meta), indent=2, sort_keys=True)}\n```\n" if message.meta else ""
        sections.append(f"### {message.role}\n\n{content}\n{meta}")
    sections.append("## Visible Tools\n")
    for tool in tools:
        sections.append(f"### {tool.name}\n\n```json\n{json.dumps(_tool_dict(tool), indent=2, sort_keys=True)}\n```\n")
    return "\n".join(sections)


def _message_dict(message: Message) -> dict[str, Any]:
    data = {"role": message.role, "content": json_safe(message.content)}
    if message.meta:
        data["meta"] = json_safe(message.meta)
    return data


def _tool_dict(tool: Tool) -> dict[str, Any]:
    return {"name": tool.name, "schema": dict(tool.schema)}


def _tool_call_dict(call: Any) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "args": call.args}
```

## `agentd/policy.py`

```python
"""Default local policy for bounded workspace execution."""

from __future__ import annotations

import re

from agentd.contracts import PolicyEngine
from agentd.state import PolicyDecision, RunState, ToolCall
from agentd.tools import patch_paths, resolve_workspace_path


class LocalPolicy:
    """Small deny-by-default policy for the built-in local tools."""

    def __init__(self, *, allow_run_artifacts: bool = False) -> None:
        self.allow_run_artifacts = allow_run_artifacts

    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        try:
            match call.name:
                case "read_file":
                    resolve_workspace_path(state, call.args["path"], allow_run_artifacts=self.allow_run_artifacts)
                    return PolicyDecision.allow("read_file path is inside workspace")
                case "list_files":
                    resolve_workspace_path(state, call.args.get("path", "."), allow_run_artifacts=self.allow_run_artifacts)
                    return PolicyDecision.allow("list_files path is inside workspace")
                case "search_repo":
                    resolve_workspace_path(state, call.args.get("path", "."), allow_run_artifacts=self.allow_run_artifacts)
                    return PolicyDecision.allow("search_repo path is inside workspace")
                case "apply_patch":
                    return self._evaluate_patch(call, state)
                case "shell":
                    return self._evaluate_shell(call)
        except Exception as exc:
            return PolicyDecision.deny(str(exc))
        return PolicyDecision.deny(f"Unknown tool for policy: {call.name}")

    def _evaluate_patch(self, call: ToolCall, state: RunState) -> PolicyDecision:
        patch = str(call.args.get("patch", ""))
        paths = patch_paths(patch)
        if not paths:
            return PolicyDecision.deny("Patch did not declare any file paths.")
        for path in paths:
            resolve_workspace_path(state, path, allow_run_artifacts=self.allow_run_artifacts)
        return PolicyDecision.allow("patch paths are inside workspace")

    def _evaluate_shell(self, call: ToolCall) -> PolicyDecision:
        cmd = str(call.args.get("cmd", ""))
        if not cmd:
            return PolicyDecision.deny("Shell command is required.")
        lower = cmd.lower()
        for pattern, reason in RISKY_SHELL_PATTERNS:
            if re.search(pattern, lower):
                return PolicyDecision.deny(reason)
        return PolicyDecision.allow("shell command passed local denylist")


RISKY_SHELL_PATTERNS = (
    (r"\bsudo\b", "sudo is denied by default."),
    (r"\brm\b(?=[^;&|]*(?:-[^\s;&|]*r|--recursive))(?=[^;&|]*(?:-[^\s;&|]*f|--force))", "recursive force removal is denied by default."),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard is denied by default."),
    (r"\bgit\s+clean\s+-[^\n;&|]*f", "git clean -f is denied by default."),
    (r"\bmkfs\b", "filesystem formatting commands are denied by default."),
    (r"\bshutdown\b|\breboot\b", "machine power commands are denied by default."),
    (r":\(\)\s*\{\s*:\|:", "fork-bomb-like shell functions are denied by default."),
)


def default_policy() -> PolicyEngine:
    return LocalPolicy()
```

## `agentd/profiles.py`

```python
"""Default profile implementations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from agentd.context import BuiltContext, ContextBuilder, ContextConfig, compact_state
from agentd.contracts import Tool
from agentd.state import Message, RunState

PROFILE_ROOT = Path(__file__).resolve().parents[1] / "profiles"


class ApexCoderProfile:
    name = "apex-coder"
    DEFAULT_VISIBLE_TOOL_NAMES = ("shell", "apply_patch")

    def __init__(
        self,
        *,
        system_prompt_path: Path | None = None,
        recent_results: int = 8,
        context_config: ContextConfig | None = None,
        recent_tool_token_budget: int | None = None,
        visible_tool_names: Sequence[str] | None = None,
    ) -> None:
        self.system_prompt_path = system_prompt_path or PROFILE_ROOT / "apex-coder" / "system.md"
        self.recent_results = recent_results
        self.visible_tool_names = tuple(visible_tool_names) if visible_tool_names is not None else self.DEFAULT_VISIBLE_TOOL_NAMES
        self.context_config = context_config or ContextConfig()
        if recent_tool_token_budget is not None:
            self.context_config = replace(self.context_config, max_recent_tool_tokens=recent_tool_token_budget)
        self._system_prompt = self._load_system_prompt()

    def system_prompt(self) -> str:
        return self._system_prompt

    def _load_system_prompt(self) -> str:
        if self.system_prompt_path.exists():
            return self.system_prompt_path.read_text()
        return (
            "You are tinyagent's default coding profile. Use shell for inspection, search, tests, and git. "
            "Use apply_patch for edits. Finish by returning assistant content when done."
        )

    def build_context(self, state: RunState) -> BuiltContext:
        return ContextBuilder(system_prompt=self.system_prompt(), config=self.context_config).build(state)

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return self.build_context(state).messages

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        return [all_tools[name] for name in self.visible_tool_names if name in all_tools]

    def should_continue(self, state: RunState) -> bool:
        return not state.done

    def should_finish(self, state: RunState) -> bool:
        return False

    def should_compact(self, state: RunState) -> bool:
        new_steps = len(state.tool_steps) - state.context_checkpoint_tool_step_count
        if new_steps <= 0:
            return False
        if self.context_config.compact_after_tool_steps > 0 and new_steps >= self.context_config.compact_after_tool_steps:
            return True
        return state.context_token_estimate >= self.context_config.effective_compact_at_tokens

    def compact(self, state: RunState) -> None:
        compact_state(state, self.context_config)
```

## `agentd/providers/__init__.py`

```python
"""Model provider adapters."""
```

## `agentd/providers/openai_compat.py`

```python
"""OpenAI-compatible Chat Completions provider."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agentd.contracts import Tool
from agentd.model_stream import ModelDelta, ProviderStreamEvent, parse_chat_completion, parse_chat_completion_chunk
from agentd.models import ProviderError
from agentd.state import Message, ModelResponse, RunState


@dataclass(frozen=True)
class OpenAICompatibleConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OpenAICompatibleConfig:
        values = os.environ if env is None else env
        base_url = values.get("TINYAGENT_MODEL_BASE_URL", "https://api.openai.com/v1")
        api_key = values.get("TINYAGENT_MODEL_API_KEY")
        model = values.get("TINYAGENT_MODEL_NAME")
        if not api_key:
            raise ProviderError("TINYAGENT_MODEL_API_KEY is required for openai-compatible provider.")
        if not model:
            raise ProviderError("TINYAGENT_MODEL_NAME is required for openai-compatible provider.")
        try:
            timeout_seconds = int(values.get("TINYAGENT_MODEL_TIMEOUT_SECONDS", "60"))
        except ValueError as exc:
            raise ProviderError("TINYAGENT_MODEL_TIMEOUT_SECONDS must be an integer.") from exc
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(self, config: OpenAICompatibleConfig) -> None:
        self.config = config

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OpenAICompatibleProvider:
        return cls(OpenAICompatibleConfig.from_env(env))

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        payload = self.build_payload(messages, tools, state)
        raw = self._post(payload)
        return parse_chat_completion(raw)

    def stream(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> Iterator[ModelDelta]:
        for event in self.stream_provider_events(messages, tools, state):
            yield from parse_chat_completion_chunk(event.raw)

    def stream_provider_events(
        self,
        messages: Sequence[Message],
        tools: Sequence[Tool],
        state: RunState,
    ) -> Iterator[ProviderStreamEvent]:
        payload = self.build_stream_payload(messages, tools, state)
        for raw in self._post_stream(payload):
            yield ProviderStreamEvent(provider=self.name, type=str(raw.get("object") or "chat.completion.chunk"), raw=raw)

    def build_payload(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [_message_payload(message) for message in messages],
        }
        if tools:
            payload["tools"] = [_tool_payload(tool) for tool in tools]
        return payload

    def build_stream_payload(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> dict[str, Any]:
        payload = self.build_payload(messages, tools, state)
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            _chat_completions_url(self.config.base_url),
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise ProviderError(f"Model provider HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Model provider request failed: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Model provider returned invalid JSON: {exc}") from exc

    def _post_stream(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            _chat_completions_url(self.config.base_url),
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode(errors="replace").strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        return
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(f"Model provider returned invalid stream JSON: {exc}") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise ProviderError(f"Model provider HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Model provider stream failed: {exc.reason}") from exc


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _message_payload(message: Message) -> dict[str, Any]:
    return {"role": message.role, "content": message.content}


def _tool_payload(tool: Tool) -> dict[str, Any]:
    schema = dict(tool.schema)
    if schema.get("type") == "function" and "function" in schema:
        return schema
    return {"type": "function", "function": schema}
```

## `agentd/replay.py`

```python
"""Replay helpers that render traces without executing side effects."""

from __future__ import annotations

from pathlib import Path

from agentd.events import Event, load_events_jsonl


def load_run_events(run_path: Path) -> list[Event]:
    path = run_path if run_path.name == "events.jsonl" else run_path / "events.jsonl"
    return load_events_jsonl(path)


def render_timeline(events: list[Event]) -> str:
    lines = ["# Tinyagent Replay", ""]
    for index, event in enumerate(events, start=1):
        detail = _event_detail(event)
        if detail:
            lines.append(f"{index:04d} {event.time.isoformat()} {event.type} {detail}")
        else:
            lines.append(f"{index:04d} {event.time.isoformat()} {event.type}")
    return "\n".join(lines) + "\n"


def replay_run(run_path: Path) -> str:
    return render_timeline(load_run_events(run_path))


def _event_detail(event: Event) -> str:
    data = event.data
    match event.type:
        case "run.started":
            return str(data.get("task", ""))
        case "run.completed":
            return f"turns={data.get('turn_count')} tools={data.get('tool_call_count')}"
        case "run.failed":
            return str(data.get("reason", ""))
        case "message.completed":
            return f"{data.get('role', 'assistant')} {data.get('content_chars')} chars {data.get('path', '')}".strip()
        case "model.request.started":
            artifacts = [
                data.get("context_artifact"),
                data.get("logical_request_artifact"),
                data.get("http_request_artifact"),
            ]
            artifact_text = " ".join(str(path) for path in artifacts if path)
            return (
                f"provider={data.get('provider')} messages={data.get('message_count')} "
                f"tools={data.get('tool_count')} {artifact_text}"
            ).strip()
        case "model.stream.started":
            return f"provider={data.get('provider')} turn={data.get('turn')}"
        case "model.completed":
            return (
                f"provider={data.get('provider')} turn={data.get('turn')} "
                f"tool_calls={data.get('tool_call_count')} finish_reason={data.get('finish_reason')} "
                f"{data.get('response_artifact') or ''}"
            )
        case "model.failed":
            return f"provider={data.get('provider')} {data.get('reason', '')}"
        case "model.usage":
            total = data.get("total_tokens")
            return f"provider={data.get('provider')} total_tokens={total}" if total is not None else f"provider={data.get('provider')}"
        case "tool.call.started" | "tool.args.completed" | "tool.execution.started" | "tool.execution.completed" | "tool.execution.failed":
            artifact = ""
            if isinstance(data.get("data"), dict):
                artifact = str(data["data"].get("output_artifact") or "")
            return f"{data.get('tool')} {data.get('tool_call_id')} {artifact}".strip()
        case "tool.policy.evaluated":
            return f"{data.get('tool')} allowed={data.get('allowed')} {data.get('reason', '')}"
        case "diff.finalized":
            return f"available={data.get('available')} chars={data.get('chars')}"
    return ""
```

## `agentd/state.py`

```python
"""State objects shared across the tinyagent kernel."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from agentd.events import Event, EventDurability, EventSink, EventVisibility, utc_now

if TYPE_CHECKING:
    from agentd.context import ContextState


def _default_context_state() -> ContextState:
    from agentd.context import ContextState

    return ContextState()


@dataclass(frozen=True)
class RunBudgets:
    max_turns: int = 30
    max_tool_calls: int = 100
    max_shell_timeout_seconds: int = 60
    max_run_seconds: int = 600
    max_command_output_chars_visible: int = 12_000

    def to_json_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class Workspace:
    root: Path

    def resolved_root(self) -> Path:
        return self.root.expanduser().resolve()

    def resolve_path(self, path: str | Path = ".") -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return candidate.resolve()

    def contains(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            return False
        return True


@dataclass(frozen=True)
class Message:
    role: str
    content: Any = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: f"call_{uuid4().hex}")


@dataclass(frozen=True)
class ToolResult:
    """A tool observation. data must stay small; large payloads belong in artifacts."""

    tool_name: str
    output: str
    call_id: str = ""
    ok: bool = True
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolStep:
    call: ToolCall
    result: ToolResult


@dataclass
class ModelResponse:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tool_calls = tuple(self.tool_calls)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""
    redacted: bool = False

    @classmethod
    def allow(cls, reason: str = "allowed") -> PolicyDecision:
        return cls(allowed=True, reason=reason)

    @classmethod
    def deny(cls, reason: str) -> PolicyDecision:
        return cls(allowed=False, reason=reason)


@dataclass
class RunState:
    run_id: str
    task: str
    workspace: Workspace
    output_dir: Path
    budgets: RunBudgets = field(default_factory=RunBudgets)
    started_at: datetime = field(default_factory=utc_now)
    events: list[Event] = field(default_factory=list)
    seq: int = 0
    tool_steps: list[ToolStep] = field(default_factory=list)
    turn_count: int = 0
    tool_call_count: int = 0
    done: bool = False
    failed: bool = False
    failure_reason: str | None = None
    final_output: str = ""
    final_diff: str = ""
    shell_preflight: dict[str, Any] = field(default_factory=dict)
    persist_events: bool = True
    stream_sink: EventSink | None = None
    context_state: ContextState = field(default_factory=_default_context_state)
    context_checkpoint: str = ""
    context_checkpoint_artifact: str = ""
    context_checkpoint_tool_step_count: int = 0
    context_token_estimate: int = 0
    compaction_count: int = 0

    @property
    def tool_results(self) -> list[ToolResult]:
        return [step.result for step in self.tool_steps]

    @classmethod
    def create(
        cls,
        task: str,
        workspace: Workspace,
        *,
        budgets: RunBudgets | None = None,
        run_id: str | None = None,
        output_dir: Path | None = None,
    ) -> RunState:
        resolved_workspace = Workspace(workspace.resolved_root())
        if not resolved_workspace.root.exists() or not resolved_workspace.root.is_dir():
            raise ValueError(f"Workspace does not exist or is not a directory: {resolved_workspace.root}")
        resolved_run_id = run_id or f"run_{uuid4().hex}"
        resolved_output_dir = (
            output_dir.expanduser().resolve()
            if output_dir
            else resolved_workspace.root / ".tinyagent" / "runs" / resolved_run_id
        )
        return cls(
            run_id=resolved_run_id,
            task=task,
            workspace=resolved_workspace,
            output_dir=resolved_output_dir,
            budgets=budgets or RunBudgets(),
        )

    def emit(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        visibility: EventVisibility = "debug",
        durability: EventDurability = "event_log",
        artifact_refs: list[str] | None = None,
        turn_id: str | None = None,
        item_id: str | None = None,
        parent_item_id: str | None = None,
    ) -> Event:
        event = Event(
            run_id=self.run_id,
            type=event_type,
            data=data or {},
            visibility=visibility,
            durability=durability,
            artifact_refs=artifact_refs or [],
            turn_id=turn_id,
            item_id=item_id,
            parent_item_id=parent_item_id,
            seq=self.seq + 1,
        )
        self.seq = event.seq
        if event.durability == "event_log":
            self.events.append(event)
        if event.durability == "event_log" and self.persist_events:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with (self.output_dir / "events.jsonl").open("a") as file:
                file.write(json.dumps(event.to_json_dict(), sort_keys=True) + "\n")
        if self.stream_sink is not None:
            self.stream_sink.emit(event)
        return event

    def elapsed_seconds(self) -> float:
        return (utc_now() - self.started_at).total_seconds()

    def fail(self, reason: str) -> None:
        if self.done:
            return
        self.done = True
        self.failed = True
        self.failure_reason = reason

    def finish(self, final_output: str = "") -> None:
        if self.done:
            return
        self.done = True
        self.final_output = final_output or self.final_output
```

## `agentd/tools/__init__.py`

```python
"""Tool collection exports."""

from __future__ import annotations

from agentd.contracts import Tool
from agentd.tools.builtins.patch import ApplyPatchTool, apply_openai_patch, patch_paths
from agentd.tools.builtins.shell import ShellTool, shell_preflight
from agentd.tools.core import (
    SAFE_ENV_KEYS,
    ToolError,
    combined_output,
    error_result,
    is_relative_to,
    relative_workspace_path,
    resolve_workspace_path,
    safe_artifact_name,
    tool_env,
    visible_output,
    write_tool_output_artifact,
)
from agentd.tools.repo import (
    EXCLUDED_SEARCH_DIRS,
    MAX_READ_FILE_BYTES,
    ListFilesTool,
    ReadFileTool,
    SearchRepoTool,
    repo_inspect_tools,
)


def builtin_tools() -> list[Tool]:
    return [ShellTool(), ApplyPatchTool()]


def all_tools() -> list[Tool]:
    return [*builtin_tools(), *repo_inspect_tools()]


def default_tools() -> list[Tool]:
    return all_tools()


__all__ = [
    "EXCLUDED_SEARCH_DIRS",
    "MAX_READ_FILE_BYTES",
    "SAFE_ENV_KEYS",
    "ApplyPatchTool",
    "ListFilesTool",
    "ReadFileTool",
    "SearchRepoTool",
    "ShellTool",
    "ToolError",
    "all_tools",
    "apply_openai_patch",
    "builtin_tools",
    "combined_output",
    "default_tools",
    "error_result",
    "is_relative_to",
    "patch_paths",
    "relative_workspace_path",
    "repo_inspect_tools",
    "resolve_workspace_path",
    "safe_artifact_name",
    "shell_preflight",
    "tool_env",
    "visible_output",
    "write_tool_output_artifact",
]
```

## `agentd/tools/builtins/__init__.py`

```python
"""Builtin tinyagent tools."""

from agentd.tools.builtins.patch import ApplyPatchTool, apply_openai_patch, patch_paths
from agentd.tools.builtins.shell import ShellTool, shell_preflight

__all__ = ["ApplyPatchTool", "ShellTool", "apply_openai_patch", "patch_paths", "shell_preflight"]
```

## `agentd/tools/builtins/patch.py`

```python
"""Builtin OpenAI-style patch tool."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agentd.state import RunState, ToolCall, ToolResult
from agentd.tools.core import (
    ToolError,
    error_result,
    relative_workspace_path,
    resolve_workspace_path,
    visible_output,
    write_tool_output_artifact,
)


class ApplyPatchTool:
    name = "apply_patch"
    schema = {
        "name": "apply_patch",
        "description": "Apply a patch inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"patch": {"type": "string"}},
            "required": ["patch"],
        },
    }

    def __init__(self, *, allow_run_artifacts: bool = False) -> None:
        self.allow_run_artifacts = allow_run_artifacts

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        patch = str(call.args.get("patch", ""))
        if not patch:
            return ToolResult(tool_name=self.name, call_id=call.id, output="patch is required", ok=False)
        try:
            touched = [
                relative_workspace_path(state, resolve_workspace_path(state, path, allow_run_artifacts=self.allow_run_artifacts))
                for path in patch_paths(patch)
            ]
        except Exception as exc:
            return error_result(self.name, call, exc)
        if not touched:
            return ToolResult(tool_name=self.name, call_id=call.id, output="patch did not declare any file paths", ok=False)

        try:
            output = apply_openai_patch(state.workspace.root, patch)
            ok = True
        except Exception as exc:
            output = str(exc)
            ok = False
        artifact = write_tool_output_artifact(state, call, "patch-output", output, kind="patch_output")
        state.emit(
            "patch.applied",
            {
                "paths": touched,
                "ok": ok,
                "output_chars": len(output),
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(output, state),
            ok=ok,
            data={"paths": touched, "output_artifact": artifact, "output_chars": len(output)},
        )


@dataclass(frozen=True)
class PatchOperation:
    action: str
    path: str
    lines: tuple[str, ...]
    move_to: str | None = None


@dataclass(frozen=True)
class _PatchSnapshot:
    existed: bool
    data: bytes | None = None


def apply_openai_patch(root: Path, patch: str) -> str:
    operations = _parse_openai_patch(patch)
    _deny_symlink_patch_paths(root, operations)
    touched_paths = _patch_touched_paths(root, operations)
    snapshots = _snapshot_patch_paths(touched_paths)
    existing_dirs = _existing_parent_dirs(root, touched_paths)
    changed: list[str] = []
    try:
        for operation in operations:
            match operation.action:
                case "add":
                    _apply_add(root, operation)
                    changed.append(f"A {operation.path}")
                case "delete":
                    _apply_delete(root, operation)
                    changed.append(f"D {operation.path}")
                case "update":
                    _apply_update(root, operation)
                    changed.append(f"M {operation.path}" if operation.move_to is None else f"R {operation.path} -> {operation.move_to}")
                case _:
                    raise ToolError(f"Unsupported patch operation: {operation.action}")
    except Exception:
        _restore_patch_snapshot(snapshots)
        _prune_new_empty_dirs(root, touched_paths, existing_dirs)
        raise
    return "Applied patch.\n" + "\n".join(changed) + ("\n" if changed else "")


def _parse_openai_patch(patch: str) -> list[PatchOperation]:
    lines = patch.splitlines()
    if not lines or lines[0] != "*** Begin Patch":
        raise ToolError("patch must start with *** Begin Patch")
    if lines[-1] != "*** End Patch":
        raise ToolError("patch must end with *** End Patch")

    operations: list[PatchOperation] = []
    index = 1
    while index < len(lines) - 1:
        line = lines[index]
        match = re.match(r"^\*\*\* (Add|Delete|Update) File: (.+)$", line)
        if not match:
            raise ToolError(f"Expected file operation, got: {line}")
        operation = match.group(1).lower()
        path = match.group(2)
        index += 1
        move_to: str | None = None
        if operation == "update" and index < len(lines) - 1:
            move_match = re.match(r"^\*\*\* Move to: (.+)$", lines[index])
            if move_match:
                move_to = move_match.group(1)
                index += 1
        body: list[str] = []
        while index < len(lines) - 1 and not lines[index].startswith("*** "):
            body.append(lines[index])
            index += 1
        operations.append(PatchOperation(action=operation, path=path, lines=tuple(body), move_to=move_to))
    return operations


def _patch_touched_paths(root: Path, operations: list[PatchOperation]) -> list[Path]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for operation in operations:
        for path in (operation.path, operation.move_to):
            if path is None:
                continue
            resolved = _patch_path(root, path)
            if resolved not in seen:
                seen.add(resolved)
                paths.append(resolved)
    return paths


def _snapshot_patch_paths(paths: list[Path]) -> dict[Path, _PatchSnapshot]:
    snapshots: dict[Path, _PatchSnapshot] = {}
    for path in paths:
        if not path.exists():
            snapshots[path] = _PatchSnapshot(existed=False)
            continue
        if not path.is_file():
            raise ToolError(f"Patch path is not a regular file: {path}")
        snapshots[path] = _PatchSnapshot(existed=True, data=path.read_bytes())
    return snapshots


def _restore_patch_snapshot(snapshots: dict[Path, _PatchSnapshot]) -> None:
    for path, snapshot in snapshots.items():
        if snapshot.existed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(snapshot.data or b"")
        elif path.exists():
            if path.is_file() or path.is_symlink():
                path.unlink()
            else:
                raise ToolError(f"Cannot roll back non-file patch path: {path}")


def _existing_parent_dirs(root: Path, paths: list[Path]) -> set[Path]:
    root = root.resolve()
    dirs = set(_parent_dirs(root, paths))
    return {path for path in dirs if path.exists()}


def _prune_new_empty_dirs(root: Path, paths: list[Path], existing_dirs: set[Path]) -> None:
    for path in sorted(_parent_dirs(root.resolve(), paths), key=lambda item: len(item.parts), reverse=True):
        if path in existing_dirs:
            continue
        try:
            path.rmdir()
        except OSError:
            continue


def _parent_dirs(root: Path, paths: list[Path]) -> set[Path]:
    dirs: set[Path] = set()
    for path in paths:
        parent = path.parent.resolve()
        while parent != root:
            try:
                parent.relative_to(root)
            except ValueError:
                break
            dirs.add(parent)
            parent = parent.parent
    return dirs


def _patch_path(root: Path, path: str) -> Path:
    root = root.resolve()
    candidate = Path(path).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ToolError(f"Path is outside workspace: {path}") from exc
    return resolved


def _raw_patch_path(root: Path, path: str) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else root / candidate


def _deny_symlink_patch_paths(root: Path, operations: list[PatchOperation]) -> None:
    for operation in operations:
        for path in (operation.path, operation.move_to):
            if path is not None and _raw_patch_path(root, path).is_symlink():
                raise ToolError(f"Cannot patch symlink path: {path}")


def _apply_add(root: Path, operation: PatchOperation) -> None:
    path = _patch_path(root, operation.path)
    if path.exists():
        raise ToolError(f"Cannot add existing file: {operation.path}")
    content = []
    for line in operation.lines:
        if not line.startswith("+"):
            raise ToolError(f"Add file lines must start with '+': {operation.path}")
        content.append(line[1:])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_join_patch_lines(content, trailing_newline=bool(content)))


def _apply_delete(root: Path, operation: PatchOperation) -> None:
    path = _patch_path(root, operation.path)
    if not path.exists():
        raise ToolError(f"Cannot delete missing file: {operation.path}")
    path.unlink()


def _apply_update(root: Path, operation: PatchOperation) -> None:
    source = _patch_path(root, operation.path)
    if not source.exists():
        raise ToolError(f"Cannot update missing file: {operation.path}")
    original_text = source.read_text(errors="replace")
    original_lines = original_text.splitlines()
    updated_lines = _apply_hunks(original_lines, operation.lines)
    target = _patch_path(root, operation.move_to or operation.path)
    if operation.move_to is not None and target.exists() and target.resolve() != source.resolve():
        raise ToolError(f"Cannot move over existing file: {operation.move_to}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_join_patch_lines(updated_lines, trailing_newline=original_text.endswith("\n")))
    if operation.move_to is not None and target.resolve() != source.resolve():
        source.unlink()


def _apply_hunks(original_lines: list[str], patch_lines: tuple[str, ...]) -> list[str]:
    if not patch_lines:
        return original_lines
    output = list(original_lines)
    cursor = 0
    for hunk in _split_hunks(patch_lines):
        old_lines = [line[1:] for line in hunk if line and line[0] in {" ", "-"}]
        new_lines = [line[1:] for line in hunk if line and line[0] in {" ", "+"}]
        position = _find_subsequence(output, old_lines, start=cursor)
        if position is None:
            raise ToolError("Patch hunk did not match file content.")
        output[position : position + len(old_lines)] = new_lines
        cursor = position + len(new_lines)
    return output


def _split_hunks(lines: tuple[str, ...]) -> list[list[str]]:
    hunks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("@@"):
            if current:
                hunks.append(current)
            current = []
            continue
        if line.startswith("\\ No newline"):
            continue
        if not line or line[0] not in {" ", "-", "+"}:
            raise ToolError(f"Invalid patch hunk line: {line}")
        current.append(line)
    if current:
        hunks.append(current)
    return hunks


def _find_subsequence(lines: list[str], needle: list[str], *, start: int) -> int | None:
    if not needle:
        return start
    stop = len(lines) - len(needle) + 1
    for index in range(start, max(stop, start)):
        if lines[index : index + len(needle)] == needle:
            return index
    return None


def _join_patch_lines(lines: list[str], *, trailing_newline: bool) -> str:
    text = "\n".join(lines)
    if trailing_newline:
        return text + "\n"
    return text


def patch_paths(patch: str) -> list[str]:
    paths: list[str] = []
    for line in patch.splitlines():
        match = re.match(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", line)
        if match:
            paths.append(match.group(1))
            continue
        match = re.match(r"^\*\*\* Move to: (.+)$", line)
        if match:
            paths.append(match.group(1))
    return paths
```

## `agentd/tools/builtins/shell.py`

```python
"""Builtin shell tool."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
from typing import Any

from agentd.state import RunState, ToolCall, ToolResult
from agentd.tools.core import combined_output, error_result, tool_env, visible_output, write_tool_output_artifact

SHELL_PREFLIGHT_COMMANDS = ("rg", "git", "python3", "python", "sed")


class ShellTool:
    name = "shell"
    schema = {
        "name": "shell",
        "description": "Run a shell command with cwd set to the workspace root.",
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "timeout_seconds": {"type": "integer", "minimum": 1},
            },
            "required": ["cmd"],
        },
    }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        cmd = str(call.args.get("cmd", ""))
        if not cmd:
            return ToolResult(tool_name=self.name, call_id=call.id, output="cmd is required", ok=False)
        try:
            requested_timeout = int(call.args.get("timeout_seconds", state.budgets.max_shell_timeout_seconds))
        except ValueError as exc:
            return error_result(self.name, call, exc)
        timeout = min(max(requested_timeout, 1), state.budgets.max_shell_timeout_seconds)
        state.emit(
            "command.started",
            {
                "tool_call_id": call.id,
                "cmd": cmd,
                "cwd": str(state.workspace.root),
                "timeout_seconds": timeout,
                "env": "sanitized",
            },
        )
        try:
            process = subprocess.Popen(
                cmd,
                cwd=state.workspace.root,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=tool_env(state),
                start_new_session=True,
            )
        except OSError as exc:
            return error_result(self.name, call, exc)

        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stdout, stderr = _terminate_process_group(process)
            output = combined_output(stdout, stderr) or f"Command timed out after {timeout}s."
            artifact = write_tool_output_artifact(state, call, "command-output", output, kind="command_output")
            state.emit(
                "command.completed",
                {
                    "tool_call_id": call.id,
                    "cmd": cmd,
                    "ok": False,
                    "timeout": True,
                    "returncode": process.returncode,
                    "output_artifact": artifact,
                    "output_chars": len(output),
                },
            )
            return ToolResult(
                tool_name=self.name,
                call_id=call.id,
                output=visible_output(output, state),
                ok=False,
                data={
                    "cmd": cmd,
                    "timeout": True,
                    "returncode": process.returncode,
                    "output_artifact": artifact,
                    "output_chars": len(output),
                },
            )

        output = combined_output(stdout, stderr) or f"Command exited {process.returncode}."
        artifact = write_tool_output_artifact(state, call, "command-output", output, kind="command_output")
        state.emit(
            "command.completed",
            {
                "tool_call_id": call.id,
                "cmd": cmd,
                "ok": process.returncode == 0,
                "timeout": False,
                "returncode": process.returncode,
                "stdout_chars": len(stdout),
                "stderr_chars": len(stderr),
                "output_artifact": artifact,
                "output_chars": len(output),
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(output, state),
            ok=process.returncode == 0,
            data={
                "cmd": cmd,
                "returncode": process.returncode,
                "output_artifact": artifact,
                "output_chars": len(output),
            },
        )


def shell_preflight() -> dict[str, Any]:
    paths = {name: shutil.which(name) for name in SHELL_PREFLIGHT_COMMANDS}
    return {
        "commands": {name: path is not None for name, path in paths.items()},
        "python_available": paths["python3"] is not None or paths["python"] is not None,
    }


def _terminate_process_group(process: subprocess.Popen[str]) -> tuple[str, str]:
    _signal_process_group(process, signal.SIGTERM)
    try:
        stdout, stderr = process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        _signal_process_group(process, signal.SIGKILL)
        stdout, stderr = process.communicate()
    return stdout or "", stderr or ""


def _signal_process_group(process: subprocess.Popen[str], sig: signal.Signals) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return
```

## `agentd/tools/core.py`

```python
"""Shared helpers for local tools."""

from __future__ import annotations

import os
import re
from pathlib import Path

from agentd.output import write_text_artifact
from agentd.state import RunState, ToolCall, ToolResult

SAFE_ENV_KEYS = frozenset(
    {
        "PATH",
        "USER",
        "USERNAME",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "SHELL",
    }
)


class ToolError(RuntimeError):
    """Raised when a local tool rejects a request before side effects."""


def resolve_workspace_path(state: RunState, path: str | Path = ".", *, allow_run_artifacts: bool = False) -> Path:
    resolved = state.workspace.resolve_path(path)
    if not state.workspace.contains(resolved):
        raise ToolError(f"Path is outside workspace: {path}")
    if not allow_run_artifacts and is_relative_to(resolved, state.output_dir.resolve()):
        raise ToolError(f"Path is inside current run artifacts: {relative_workspace_path(state, resolved)}")
    return resolved


def relative_workspace_path(state: RunState, path: Path) -> str:
    try:
        return path.resolve().relative_to(state.workspace.root).as_posix()
    except ValueError:
        return str(path)


def combined_output(stdout: str, stderr: str) -> str:
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr


def write_tool_output_artifact(state: RunState, call: ToolCall, prefix: str, output: str, *, kind: str) -> str:
    return write_text_artifact(state, f"{prefix}-{safe_artifact_name(call.id)}.txt", output, kind=kind)


def visible_output(output: str, state: RunState) -> str:
    limit = state.budgets.max_command_output_chars_visible
    if len(output) <= limit:
        return output
    marker = "\n[truncated]"
    if limit <= len(marker):
        return output[:limit]
    return output[: limit - len(marker)] + marker


def safe_artifact_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "call")


def tool_env(state: RunState) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
    home = state.output_dir / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    return env


def error_result(tool_name: str, call: ToolCall, exc: Exception) -> ToolResult:
    return ToolResult(tool_name=tool_name, call_id=call.id, output=str(exc), ok=False, data={"error_type": type(exc).__name__})


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
```

## `agentd/tools/repo.py`

```python
"""Optional repo inspection tools."""

from __future__ import annotations

import os
import selectors
import shutil
import subprocess
import time
from pathlib import Path

from agentd.contracts import Tool
from agentd.state import RunState, ToolCall, ToolResult
from agentd.tools.core import (
    error_result,
    is_relative_to,
    relative_workspace_path,
    resolve_workspace_path,
    tool_env,
    write_tool_output_artifact,
)

EXCLUDED_SEARCH_DIRS = frozenset({".git", ".tinyagent"})
MAX_READ_FILE_BYTES = 1_000_000


class ReadFileTool:
    name = "read_file"
    schema = {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "max_lines": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        },
    }

    def __init__(self, *, allow_run_artifacts: bool = False) -> None:
        self.allow_run_artifacts = allow_run_artifacts

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        try:
            path = resolve_workspace_path(state, call.args["path"], allow_run_artifacts=self.allow_run_artifacts)
            start_line = max(int(call.args.get("start_line", 1)), 1)
            max_lines = max(int(call.args.get("max_lines", 400)), 1)
            file_size = path.stat().st_size
            if file_size > MAX_READ_FILE_BYTES:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call.id,
                    output=f"file is too large to read: {relative_workspace_path(state, path)} ({file_size} bytes)",
                    ok=False,
                    data={"path": relative_workspace_path(state, path), "bytes": file_size, "max_bytes": MAX_READ_FILE_BYTES},
                )
            text = path.read_text(errors="replace")
        except Exception as exc:
            return error_result(self.name, call, exc)

        lines = text.splitlines()
        selected = lines[start_line - 1 : start_line - 1 + max_lines]
        numbered = "\n".join(f"{index}: {line}" for index, line in enumerate(selected, start=start_line))
        rel_path = relative_workspace_path(state, path)
        state.emit(
            "file.read",
            {
                "path": rel_path,
                "start_line": start_line,
                "line_count": len(selected),
                "total_lines": len(lines),
                "bytes": len(text.encode()),
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=f"{rel_path}\n{numbered}" if numbered else f"{rel_path}\n",
            data={"path": rel_path, "line_count": len(selected), "total_lines": len(lines)},
        )


class ListFilesTool:
    name = "list_files"
    schema = {
        "name": "list_files",
        "description": "List files inside the workspace, excluding trace and git directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_files": {"type": "integer", "minimum": 1},
            },
        },
    }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        try:
            root = resolve_workspace_path(state, call.args.get("path", "."), allow_run_artifacts=True)
            max_files = max(int(call.args.get("max_files", 200)), 1)
            files = list(_iter_workspace_files(state, root, max_files=max_files + 1))
        except Exception as exc:
            return error_result(self.name, call, exc)

        truncated = len(files) > max_files
        visible = files[:max_files]
        output = "\n".join(relative_workspace_path(state, path) for path in visible)
        state.emit(
            "files.listed",
            {
                "path": relative_workspace_path(state, root),
                "file_count": len(visible),
                "truncated": truncated,
                "excluded": _excluded_search_labels(state),
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=output,
            data={"file_count": len(visible), "truncated": truncated},
        )


class SearchRepoTool:
    name = "search_repo"
    schema = {
        "name": "search_repo",
        "description": "Search text inside workspace files, excluding trace and git directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "max_matches": {"type": "integer", "minimum": 1},
            },
            "required": ["query"],
        },
    }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        query = str(call.args.get("query", ""))
        if not query:
            return ToolResult(tool_name=self.name, call_id=call.id, output="query is required", ok=False)
        try:
            path = resolve_workspace_path(state, call.args.get("path", "."), allow_run_artifacts=True)
            max_matches = max(int(call.args.get("max_matches", 100)), 1)
        except Exception as exc:
            return error_result(self.name, call, exc)

        try:
            output, captured_output, match_count, truncated, used_rg, timed_out = _search_workspace(
                state,
                path,
                query,
                max_matches=max_matches,
            )
        except Exception as exc:
            return error_result(self.name, call, exc)
        artifact = write_tool_output_artifact(
            state,
            call,
            "search-output",
            captured_output or "No matches.",
            kind="search_captured_output",
        )
        state.emit(
            "search.completed",
            {
                "query": query,
                "path": relative_workspace_path(state, path),
                "match_count": match_count,
                "truncated": truncated,
                "timed_out": timed_out,
                "used_rg": used_rg,
                "excluded": _excluded_search_labels(state),
                "captured_output_artifact": artifact,
                "captured_output_chars": len(captured_output or "No matches."),
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=output or "No matches.",
            data={
                "query": query,
                "path": relative_workspace_path(state, path),
                "match_count": match_count,
                "truncated": truncated,
                "timed_out": timed_out,
                "used_rg": used_rg,
                "captured_output_artifact": artifact,
                "captured_output_chars": len(captured_output or "No matches."),
                "output_artifact": artifact,
                "output_chars": len(captured_output or "No matches."),
            },
        )


def repo_inspect_tools() -> list[Tool]:
    return [ReadFileTool(), ListFilesTool(), SearchRepoTool()]


def _iter_workspace_files(state: RunState, root: Path, *, max_files: int) -> list[Path]:
    if root.is_file():
        return [root] if not _excluded(state, root) else []
    if _excluded(state, root):
        return []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if path.is_file() and not _excluded(state, path):
            files.append(path)
    return files


def _search_workspace(state: RunState, path: Path, query: str, *, max_matches: int) -> tuple[str, str, int, bool, bool, bool]:
    if _excluded(state, path):
        return "", "", 0, False, False, False

    rg = shutil.which("rg")
    if rg is not None:
        target = relative_workspace_path(state, path)
        lines, truncated, timed_out = _run_rg_limited(state, rg, query, target, max_matches=max_matches)
        visible = lines[:max_matches]
        captured_output = "\n".join(lines)
        return "\n".join(visible), captured_output, len(visible), truncated, True, timed_out

    matches: list[str] = []
    deadline = time.monotonic() + max(state.budgets.max_shell_timeout_seconds, 1)
    for file_path in _iter_workspace_files(state, path, max_files=100_000):
        if time.monotonic() >= deadline:
            return "\n".join(matches[:max_matches]), "\n".join(matches), min(len(matches), max_matches), True, False, True
        try:
            if file_path.stat().st_size > MAX_READ_FILE_BYTES:
                continue
            text = file_path.read_text(errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                matches.append(f"{relative_workspace_path(state, file_path)}:{line_number}:{line}")
                if len(matches) >= max_matches + 1:
                    return "\n".join(matches[:max_matches]), "\n".join(matches), max_matches, True, False, False
    output = "\n".join(matches)
    return output, output, len(matches), False, False, False


def _run_rg_limited(state: RunState, rg: str, query: str, target: str, *, max_matches: int) -> tuple[list[str], bool, bool]:
    command = [
        rg,
        "--line-number",
        "--no-heading",
        "--color",
        "never",
        "--max-filesize",
        "2M",
        "--max-columns",
        "300",
        "--glob",
        "!**/.tinyagent/**",
        "--glob",
        "!**/.git/**",
    ]
    command.extend(_rg_exclude_output_dir_args(state))
    command.extend(["--", query, target])
    process = subprocess.Popen(
        command,
        cwd=state.workspace.root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=tool_env(state),
    )
    assert process.stdout is not None
    lines: list[str] = []
    truncated = False
    timed_out = False
    buffer = b""
    deadline = time.monotonic() + max(state.budgets.max_shell_timeout_seconds, 1)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while process.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                truncated = True
                process.terminate()
                break
            events = selector.select(timeout=min(0.1, remaining))
            if not events:
                continue
            chunk = os.read(process.stdout.fileno(), 8192)
            if not chunk:
                break
            buffer = _append_rg_chunk(buffer, chunk, lines)
            if len(lines) > max_matches:
                truncated = True
                process.terminate()
                break
        while not timed_out and len(lines) <= max_matches:
            chunk = os.read(process.stdout.fileno(), 8192)
            if not chunk:
                break
            buffer = _append_rg_chunk(buffer, chunk, lines)
        if buffer and len(lines) <= max_matches:
            lines.append(buffer.decode(errors="replace").rstrip("\r"))
        if len(lines) > max_matches:
            truncated = True
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
    finally:
        selector.close()
        process.stdout.close()
    return lines, truncated, timed_out


def _append_rg_chunk(buffer: bytes, chunk: bytes, lines: list[str]) -> bytes:
    buffer += chunk
    while b"\n" in buffer:
        raw_line, buffer = buffer.split(b"\n", 1)
        lines.append(raw_line.decode(errors="replace").rstrip("\r"))
    return buffer


def _excluded(state: RunState, path: Path) -> bool:
    try:
        resolved = path.resolve()
        parts = resolved.relative_to(state.workspace.root).parts
    except ValueError:
        return True
    if any(part in EXCLUDED_SEARCH_DIRS for part in parts):
        return True
    return _output_dir_inside_workspace(state) is not None and is_relative_to(resolved, state.output_dir.resolve())


def _rg_exclude_output_dir_args(state: RunState) -> list[str]:
    relative = _output_dir_inside_workspace(state)
    if relative is None:
        return []
    return ["--glob", f"!{relative}", "--glob", f"!{relative}/**"]


def _excluded_search_labels(state: RunState) -> list[str]:
    excluded = set(EXCLUDED_SEARCH_DIRS)
    relative = _output_dir_inside_workspace(state)
    if relative is not None:
        excluded.add(relative)
    return sorted(excluded)


def _output_dir_inside_workspace(state: RunState) -> str | None:
    try:
        return state.output_dir.resolve().relative_to(state.workspace.root).as_posix()
    except ValueError:
        return None
```
