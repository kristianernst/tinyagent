"""Pure progress guardrails for repeated no-progress tool loops."""

from __future__ import annotations

import json
from dataclasses import dataclass

from tinyagent.core.state import RunState, ToolCall


@dataclass(frozen=True)
class ProgressDecision:
    allow: bool
    reason: str = ""

    @classmethod
    def allowed(cls) -> ProgressDecision:
        return cls(True)

    @classmethod
    def blocked(cls, reason: str) -> ProgressDecision:
        return cls(False, reason)


class ProgressGuard:
    def before_tool_call(self, state: RunState, call: ToolCall) -> ProgressDecision:
        if call.name != "shell":
            key = _tool_call_key(call)
            if _same_successful_tool_call_count_since_mutation(state, key) >= 2:
                return ProgressDecision.blocked(
                    "Progress guard blocked repeated tool call with identical input and no file changes since the earlier "
                    f"successful calls: {key}. The output has already been returned; use that evidence or choose different input."
                )
        if call.name == "shell":
            cmd = _normalized_cmd(call)
            if _failed_same_shell_command_count(state, cmd) >= 2:
                return ProgressDecision.blocked(
                    f"Progress guard blocked repeated failed command: `{cmd}`. Change approach before retrying."
                )
            if _is_read_only_command(cmd) and _same_successful_read_count(state, cmd) >= 2:
                return ProgressDecision.blocked(
                    f"Progress guard blocked repeated read-only command with no new evidence: `{cmd}`. "
                    "Use the evidence already collected or inspect a different target."
                )
        if call.name == "apply_patch":
            patch = str(call.args.get("patch") or "")
            if patch and _failed_same_patch_count(state, patch) >= 2:
                return ProgressDecision.blocked(
                    "Progress guard blocked repeated patch failure. Inspect the file and change the patch before retrying."
                )
        return ProgressDecision.allowed()


def _normalized_cmd(call: ToolCall) -> str:
    return " ".join(str(call.args.get("cmd") or "").split())


def _tool_call_key(call: ToolCall) -> str:
    try:
        args = json.dumps(call.args, sort_keys=True, ensure_ascii=False)
    except TypeError:
        args = repr(call.args)
    return f"{call.name}({args})"


def _same_successful_tool_call_count_since_mutation(state: RunState, key: str) -> int:
    count = 0
    checkpoint = max(state.context_checkpoint_tool_step_count, 0)
    for step in reversed(state.tool_steps[checkpoint:]):
        if _step_mutated_workspace(step):
            break
        if not step.result.ok:
            continue
        if _tool_call_key(step.call) == key:
            count += 1
    return count


def _step_mutated_workspace(step: object) -> bool:
    metadata = getattr(getattr(step, "result", None), "metadata", {})
    if isinstance(metadata, dict):
        delta = metadata.get("workspace_delta")
        if isinstance(delta, dict) and delta.get("mutated"):
            return True
    data = getattr(getattr(step, "result", None), "data", {})
    if isinstance(data, dict):
        delta = data.get("workspace_delta")
        if isinstance(delta, dict) and delta.get("mutated"):
            return True
    return False


def _failed_same_shell_command_count(state: RunState, cmd: str) -> int:
    return sum(
        1
        for step in state.tool_steps
        if step.call.name == "shell" and _normalized_cmd(step.call) == cmd and not step.result.ok
    )


def _same_successful_read_count(state: RunState, cmd: str) -> int:
    return sum(
        1
        for step in state.tool_steps
        if step.call.name == "shell" and _normalized_cmd(step.call) == cmd and step.result.ok
    )


def _failed_same_patch_count(state: RunState, patch: str) -> int:
    return sum(
        1
        for step in state.tool_steps
        if step.call.name == "apply_patch" and str(step.call.args.get("patch") or "") == patch and not step.result.ok
    )


def _is_read_only_command(cmd: str) -> bool:
    first = cmd.split(maxsplit=1)[0] if cmd else ""
    return first in {"cat", "sed", "head", "tail", "rg", "grep", "find", "ls"}
