"""Builtin shell tool."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from typing import Any

from agentd.run_control import RunCancelled
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
            stdout, stderr = _communicate_with_cancel(process, state, timeout)
        except subprocess.TimeoutExpired:
            stdout, stderr = _terminate_process_group(process)
            output = combined_output(stdout, stderr) or f"Command timed out after {timeout}s."
            artifact = write_tool_output_artifact(state, call, "command-output", output, kind="command_output")
            state.emit(
                "command.timeout",
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
        except RunCancelled:
            state.request_cancel(
                state.cancel_token.reason or "cancelled",
                source="sigint" if state.cancel_token.reason == "sigint" else "harness",
                escalate=state.cancel_token.escalated,
            )
            stdout, stderr = _terminate_process_group(process)
            output = combined_output(stdout, stderr) or "Command cancelled."
            artifact = write_tool_output_artifact(state, call, "command-output", output, kind="command_output")
            state.emit(
                "command.cancelled",
                {
                    "tool_call_id": call.id,
                    "cmd": cmd,
                    "reason": state.cancel_reason or "cancelled",
                    "returncode": process.returncode,
                    "output_artifact": artifact,
                    "output_chars": len(output),
                    "escalated": state.cancel_escalated,
                },
                visibility="user",
            )
            return ToolResult(
                tool_name=self.name,
                call_id=call.id,
                output=visible_output(output, state),
                ok=False,
                data={
                    "cmd": cmd,
                    "cancelled": True,
                    "reason": state.cancel_reason or "cancelled",
                    "returncode": process.returncode,
                    "output_artifact": artifact,
                    "output_chars": len(output),
                },
            )

        output = combined_output(stdout, stderr) or f"Command exited {process.returncode}."
        artifact = write_tool_output_artifact(state, call, "command-output", output, kind="command_output")
        state.emit(
            "command.completed" if process.returncode == 0 else "command.failed",
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
