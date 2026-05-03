"""Pure progress guardrails for repeated no-progress tool loops."""

from __future__ import annotations

from dataclasses import dataclass

from agentd.state import RunState, ToolCall


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
