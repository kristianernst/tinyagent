"""Execution envelope metadata for local tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from agentd.state import RunState
from agentd.tools.core import tool_env


@dataclass(frozen=True)
class ExecutionEnvelope:
    cwd: Path
    env: dict[str, str] = field(repr=False, compare=False)
    timeout_seconds: int
    output_cap_chars: int
    writable_roots: tuple[Path, ...]
    network_policy: str = "policy_gated"
    sandbox_backend: str = "none"
    sandbox_enforced: bool = False
    process_group_cancellation: bool = True

    def to_json_dict(self) -> dict[str, object]:
        return {
            "cwd": str(self.cwd),
            "env": "sanitized",
            "timeout_seconds": self.timeout_seconds,
            "output_cap_chars": self.output_cap_chars,
            "writable_roots": [str(path) for path in self.writable_roots],
            "network_policy": self.network_policy,
            "sandbox_backend": self.sandbox_backend,
            "sandbox_enforced": self.sandbox_enforced,
            "process_group_cancellation": self.process_group_cancellation,
        }


def build_execution_envelope(state: RunState, *, timeout_seconds: int) -> ExecutionEnvelope:
    workspace_envelope = state.workspace_envelope
    return ExecutionEnvelope(
        cwd=state.workspace.root,
        env=tool_env(state),
        timeout_seconds=timeout_seconds,
        output_cap_chars=state.budgets.max_command_output_chars_visible,
        writable_roots=(state.workspace.root,),
        sandbox_backend=workspace_envelope.sandbox_mode if workspace_envelope else "none",
        sandbox_enforced=bool(workspace_envelope.sandbox_enforced) if workspace_envelope else False,
    )
