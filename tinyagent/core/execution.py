"""Execution envelope metadata for local tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tinyagent.core.container_sandbox import CONTAINER_HOME, CONTAINER_WORKDIR, container_backend_version, default_container_image
from tinyagent.core.state import RunState
from tinyagent.core.tools.core import tool_env
from tinyagent.core.workspace import NetworkMode, SandboxBackend


@dataclass(frozen=True)
class ExecutionEnvelope:
    cwd: Path
    env: dict[str, str] = field(repr=False, compare=False)
    timeout_seconds: int
    output_cap_chars: int
    read_roots: tuple[Path, ...]
    writable_roots: tuple[Path, ...]
    denied_paths: tuple[Path, ...] = ()
    network_mode: NetworkMode = "ask"
    network_policy: str = "policy_gated"
    sandbox_backend: SandboxBackend = "none"
    sandbox_backend_version: str = ""
    sandbox_enforced: bool = False
    container_image: str = ""
    container_workdir: str = CONTAINER_WORKDIR
    container_home: str = CONTAINER_HOME
    container_home_host: Path | None = None
    git_access_mode: str = "workspace"
    escalation_hint: str = "Requests outside the local policy require approval; no real sandbox backend is active."
    process_group_cancellation: bool = True

    def to_json_dict(self) -> dict[str, object]:
        return {
            "cwd": str(self.cwd),
            "env": "sanitized",
            "timeout_seconds": self.timeout_seconds,
            "output_cap_chars": self.output_cap_chars,
            "read_roots": [str(path) for path in self.read_roots],
            "writable_roots": [str(path) for path in self.writable_roots],
            "denied_paths": [str(path) for path in self.denied_paths],
            "network_mode": self.network_mode,
            "network_policy": self.network_policy,
            "sandbox_backend": self.sandbox_backend,
            "sandbox_backend_version": self.sandbox_backend_version,
            "sandbox_enforced": self.sandbox_enforced,
            "container_image": self.container_image,
            "container_workdir": self.container_workdir,
            "container_home": self.container_home,
            "container_home_host": str(self.container_home_host) if self.container_home_host else None,
            "git_access_mode": self.git_access_mode,
            "escalation_hint": self.escalation_hint,
            "process_group_cancellation": self.process_group_cancellation,
        }


def build_execution_envelope(state: RunState, *, timeout_seconds: int) -> ExecutionEnvelope:
    workspace_envelope = state.workspace_envelope
    sandbox_backend = workspace_envelope.sandbox_backend if workspace_envelope else "none"
    sandbox_enforced = bool(workspace_envelope.sandbox_enforced) if workspace_envelope else False
    container_home_host = state.output_dir / "container-home" if sandbox_enforced and sandbox_backend in {"docker", "podman"} else None
    writable_roots = (state.workspace.root, container_home_host or state.output_dir / "home")
    return ExecutionEnvelope(
        cwd=state.workspace.root,
        env=tool_env(state),
        timeout_seconds=timeout_seconds,
        output_cap_chars=state.budgets.max_command_output_chars_visible,
        read_roots=(state.workspace.root,),
        writable_roots=writable_roots,
        denied_paths=(state.output_dir / "artifacts", state.output_dir / "context", state.output_dir / "events.jsonl"),
        network_mode=workspace_envelope.network_mode if workspace_envelope else "deny",
        sandbox_backend=sandbox_backend,
        sandbox_backend_version=container_backend_version(sandbox_backend) if sandbox_enforced else "",
        sandbox_enforced=sandbox_enforced,
        container_image=default_container_image() if sandbox_enforced else "",
        container_home_host=container_home_host,
        escalation_hint=(
            "Container sandbox is active for shell execution; network is denied unless policy and backend mode allow it."
            if sandbox_enforced
            else "Requests outside the local policy require approval; no real sandbox backend is active."
        ),
    )
