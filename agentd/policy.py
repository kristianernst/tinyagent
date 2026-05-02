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
