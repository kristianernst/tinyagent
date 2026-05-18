"""Builtin shell tool."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tinyagent.core.container_sandbox import ContainerSandboxConfig, build_container_command
from tinyagent.core.contracts import ToolRuntime
from tinyagent.core.execution import build_execution_envelope
from tinyagent.core.run_control import RunCancelled
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.token_utils import estimate_tokens
from tinyagent.core.tools.core import ToolOutputCapture, capture_tool_output, combined_output, duration_ms, error_result

SHELL_PREFLIGHT_COMMANDS = ("rg", "git", "python3", "python", "sed")


@dataclass(frozen=True)
class _ProcessLaunch:
    args: str | list[str]
    shell: bool
    container_backend: str = ""
    cidfile: Path | None = None


class ShellTool:
    name = "shell"
    runtime = ToolRuntime(parallel_safe=False, mutates_workspace=True, requires_shell=True, lock_key="shell")
    schema = {
        "name": "shell",
        "description": (
            "Run a shell command with cwd set to the workspace root. Results include an execution_envelope "
            "with read/write roots, network mode, git access, sandbox backend, and escalation hints."
        ),
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
        started = time.monotonic()
        cmd = str(call.args.get("cmd", ""))
        if not cmd:
            return ToolResult(tool_name=self.name, call_id=call.id, output="cmd is required", ok=False)
        try:
            requested_timeout = int(call.args.get("timeout_seconds", state.budgets.max_shell_timeout_seconds))
        except ValueError as exc:
            return error_result(self.name, call, exc)
        timeout = min(max(requested_timeout, 1), state.budgets.max_shell_timeout_seconds)
        envelope = build_execution_envelope(state, timeout_seconds=timeout)
        state.emit(
            "command.started",
            {
                "tool_call_id": call.id,
                "cmd": cmd,
                "cwd": str(envelope.cwd),
                "timeout_seconds": timeout,
                "env": "sanitized",
                "execution_envelope": envelope.to_json_dict(),
            },
        )
        try:
            launch = _popen_command(cmd, envelope, call.id)
            process = subprocess.Popen(
                launch.args,
                cwd=envelope.cwd,
                shell=launch.shell,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=envelope.env,
                start_new_session=True,
            )
        except OSError as exc:
            return error_result(self.name, call, exc)

        try:
            stdout, stderr = _communicate_with_cancel(process, state, timeout)
        except subprocess.TimeoutExpired:
            _terminate_container(launch)
            stdout, stderr = _terminate_process_group(process)
            output = combined_output(stdout, stderr) or f"Command timed out after {timeout}s."
            return _finish_command(
                state,
                call,
                started,
                envelope,
                cmd,
                process,
                output,
                event_type="command.timeout",
                ok=False,
                summary=f"Command timed out after {timeout}s.",
                failure_kind="timeout",
                recoverability="increase_timeout_or_simplify",
                event_extra={"ok": False, "timeout": True, "returncode": process.returncode},
                data_extra={"timeout": True},
            )
        except RunCancelled:
            state.request_cancel(
                state.cancel_token.reason or "cancelled",
                source="sigint" if state.cancel_token.reason == "sigint" else "harness",
                escalate=state.cancel_token.escalated,
            )
            _terminate_container(launch)
            stdout, stderr = _terminate_process_group(process)
            output = combined_output(stdout, stderr) or "Command cancelled."
            reason = state.cancel_reason or "cancelled"
            return _finish_command(
                state,
                call,
                started,
                envelope,
                cmd,
                process,
                output,
                event_type="command.cancelled",
                ok=False,
                summary=reason,
                failure_kind="user_aborted",
                recoverability="rerun_if_needed",
                event_extra={"reason": reason, "returncode": process.returncode, "escalated": state.cancel_escalated},
                data_extra={"cancelled": True, "reason": reason},
                visibility="user",
            )

        output = combined_output(stdout, stderr) or f"Command exited {process.returncode}."
        ok = process.returncode == 0
        failure_kind = None if ok else "command_failed"
        return _finish_command(
            state,
            call,
            started,
            envelope,
            cmd,
            process,
            output,
            event_type="command.completed" if ok else "command.failed",
            ok=ok,
            summary=f"Command exited {process.returncode}.",
            failure_kind=failure_kind,
            recoverability="inspect_output",
            event_extra={
                "ok": ok,
                "timeout": False,
                "returncode": process.returncode,
                "stdout_tokens": estimate_tokens(stdout),
                "stderr_tokens": estimate_tokens(stderr),
            },
            metadata_extra={"stdout_tokens": estimate_tokens(stdout), "stderr_tokens": estimate_tokens(stderr)},
        )


def _capture_shell_output(state: RunState, call: ToolCall, output: str) -> ToolOutputCapture:
    return capture_tool_output(state, call, output, prefix="command-output", kind="command_output", context_kind="shell_output")


def _finish_command(
    state: RunState,
    call: ToolCall,
    started: float,
    envelope: Any,
    cmd: str,
    process: subprocess.Popen[str],
    output: str,
    *,
    event_type: str,
    ok: bool,
    summary: str,
    failure_kind: str | None,
    recoverability: str,
    event_extra: dict[str, Any],
    data_extra: dict[str, Any] | None = None,
    metadata_extra: dict[str, Any] | None = None,
    visibility: str = "debug",
) -> ToolResult:
    captured = _capture_shell_output(state, call, output)
    elapsed_ms = duration_ms(started)
    failure_data = _failure_data(failure_kind, capability="process", source="tool", recoverability=recoverability)
    state.emit(
        event_type,
        {
            "tool_call_id": call.id,
            "cmd": cmd,
            **event_extra,
            **captured.data,
            "duration_ms": elapsed_ms,
            "failure_kind": failure_kind,
            **failure_data,
            "execution_envelope": envelope.to_json_dict(),
        },
        visibility=visibility,
    )
    return captured.tool_result(
        call.name,
        call,
        ok=ok,
        exit_code=process.returncode,
        duration_ms=elapsed_ms,
        summary=summary,
        failure_kind=failure_kind,
        data={
            "cmd": cmd,
            "returncode": process.returncode,
            **(data_extra or {}),
            **captured.data,
            "duration_ms": elapsed_ms,
            "failure_kind": failure_kind,
            **failure_data,
        },
        metadata=_command_metadata(envelope, cmd, **(metadata_extra or {})),
        failure=not ok,
    )


def _command_metadata(envelope: Any, cmd: str, **extra: Any) -> dict[str, Any]:
    return {
        "cwd": str(envelope.cwd),
        **extra,
        "command_normalized": cmd,
        "execution_envelope": envelope.to_json_dict(),
    }


def _communicate_with_cancel(process: subprocess.Popen[str], state: RunState, timeout: int) -> tuple[str, str]:
    deadline = time.monotonic() + timeout
    while True:
        state.raise_if_cancelled()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        try:
            return process.communicate(timeout=min(0.1, remaining))
        except subprocess.TimeoutExpired:
            continue


def shell_preflight(state: RunState | None = None) -> dict[str, Any]:
    paths = {name: shutil.which(name) for name in SHELL_PREFLIGHT_COMMANDS}
    sandboxed = bool(state and state.workspace_envelope and state.workspace_envelope.sandbox_enforced)
    return {
        "commands": {name: path is not None for name, path in paths.items()},
        "python_available": paths["python3"] is not None or paths["python"] is not None,
        "scope": "host" if not sandboxed else "host-preflight-for-container",
        "authoritative": not sandboxed,
    }


def _popen_command(cmd: str, envelope, call_id: str = "shell") -> _ProcessLaunch:
    if not envelope.sandbox_enforced or envelope.sandbox_backend not in {"docker", "podman"}:
        return _ProcessLaunch(args=cmd, shell=True)
    if envelope.container_home_host is None:
        raise OSError("container sandbox home directory is not configured")
    envelope.container_home_host.mkdir(parents=True, exist_ok=True)
    cid_dir = envelope.container_home_host.parent / "container-cids"
    cid_dir.mkdir(parents=True, exist_ok=True)
    cidfile = cid_dir / f"{_safe_name(call_id)}.cid"
    try:
        cidfile.unlink()
    except FileNotFoundError:
        pass
    config = ContainerSandboxConfig(
        backend=envelope.sandbox_backend,
        image=envelope.container_image,
        workspace_host=envelope.cwd,
        home_host=envelope.container_home_host,
        cidfile_host=cidfile,
        network_mode=envelope.network_mode,
        uid=os.getuid(),
        gid=os.getgid(),
    )
    return _ProcessLaunch(
        args=build_container_command(config, cmd),
        shell=False,
        container_backend=envelope.sandbox_backend,
        cidfile=cidfile,
    )


def _terminate_container(launch: _ProcessLaunch) -> None:
    if not launch.container_backend or launch.cidfile is None:
        return
    try:
        container_id = launch.cidfile.read_text().strip()
    except OSError:
        return
    if not container_id:
        return
    for args in (["kill", container_id], ["rm", "-f", container_id]):
        try:
            subprocess.run([launch.container_backend, *args], capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value) or "shell"


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


def _failure_data(failure_kind: str | None, *, capability: str, source: str, recoverability: str) -> dict[str, str]:
    if not failure_kind:
        return {}
    return {
        "failure_kind": failure_kind,
        "capability": capability,
        "source": source,
        "recoverability": recoverability,
    }
