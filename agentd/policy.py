"""Default local policy for bounded workspace execution."""

from __future__ import annotations

import re
from pathlib import Path

from agentd.contracts import PolicyEngine
from agentd.state import ApprovalRequest, PolicyDecision, RunState, ToolCall
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
                    return self._evaluate_shell(call, state)
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
        if _dirty_current_workspace(state):
            return PolicyDecision.needs_approval(
                "patch would mutate a dirty current workspace",
                _approval_request(call, state, action_kind="dirty_mutation", risk="medium"),
            )
        return PolicyDecision.allow("patch paths are inside workspace")

    def _evaluate_shell(self, call: ToolCall, state: RunState) -> PolicyDecision:
        cmd = str(call.args.get("cmd", ""))
        if not cmd:
            return PolicyDecision.deny("Shell command is required.")
        lower = cmd.lower()
        for pattern, reason in RISKY_SHELL_PATTERNS:
            if re.search(pattern, lower):
                return PolicyDecision.deny(reason)
        redirect_escape = _outside_redirect_target(cmd, state)
        if redirect_escape:
            return PolicyDecision.needs_approval(
                f"shell redirects outside workspace envelope: {redirect_escape}",
                _approval_request(
                    call,
                    state,
                    action_kind="workspace_escape",
                    risk="high",
                    args_preview=cmd,
                    command=cmd,
                ),
            )
        if _NETWORK_SHELL_PATTERN.search(lower):
            return PolicyDecision.needs_approval(
                "network-looking shell command requires approval",
                _approval_request(call, state, action_kind="network", risk="high", args_preview=cmd, command=cmd),
            )
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

_NETWORK_SHELL_PATTERN = re.compile(r"\b(curl|wget|ssh|scp|sftp|rsync|nc|ncat|telnet)\b")
_REDIRECT_PATTERN = re.compile(r"(?:^|[\s;&|])(?:>|>>|<)\s*(?P<path>[^()\s;&|]+)")


def _dirty_current_workspace(state: RunState) -> bool:
    envelope = state.workspace_envelope
    if envelope is None or envelope.effective_mode != "current":
        return False
    dirty = envelope.dirty_state_before
    return dirty.is_git_repo and not dirty.clean


def _outside_redirect_target(cmd: str, state: RunState) -> str:
    for match in _REDIRECT_PATTERN.finditer(cmd):
        raw = match.group("path").strip("'\"")
        if not raw or raw.startswith("&"):
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            continue
        envelope = state.workspace_envelope
        if envelope is not None:
            if not envelope.contains(path):
                return raw
        elif not state.workspace.contains(path):
            return raw
    return ""


def _approval_request(
    call: ToolCall,
    state: RunState,
    *,
    action_kind: str,
    risk: str,
    args_preview: str | None = None,
    command: str | None = None,
) -> ApprovalRequest:
    preview = args_preview if args_preview is not None else str(call.args)
    return ApprovalRequest(
        approval_id=f"approval_{call.id}",
        run_id=state.run_id,
        turn_id=state.current_turn_id,
        step_id=state.current_step_id,
        action_kind=action_kind,  # type: ignore[arg-type]
        tool_name=call.name,
        cwd=str(state.workspace.root),
        args_preview=preview[:1000],
        command=command,
        risk=risk,  # type: ignore[arg-type]
    )


def default_policy() -> PolicyEngine:
    return LocalPolicy()
