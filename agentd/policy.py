"""Default local policy for bounded workspace execution."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal

from agentd.contracts import PolicyEngine
from agentd.state import ApprovalRequest, PolicyDecision, RunState, ToolCall
from agentd.tools import patch_paths, resolve_workspace_path


class LocalPolicy:
    """Classifier-first local policy for permissive workspace bash.

    This is not a sandbox. Network, secrets, ContextFS/evidence writes,
    external redirects, repeated failures, and known destructive commands are
    restricted before the default bash allow rule applies.
    """

    def __init__(self, *, allow_run_artifacts: bool = False, config: PolicyConfig | None = None) -> None:
        self.allow_run_artifacts = allow_run_artifacts
        self.config = config or default_policy_config()

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
                case "read_context":
                    return PolicyDecision.allow("read_context path is constrained to safe ContextFS recovery files")
                case "apply_patch" | "str_replace_edit" | "write_file":
                    return self._evaluate_patch(call, state)
                case "shell":
                    return self._evaluate_shell(call, state)
        except Exception as exc:
            return PolicyDecision.deny(str(exc))
        return PolicyDecision.deny(f"Unknown tool for policy: {call.name}")

    def _evaluate_patch(self, call: ToolCall, state: RunState) -> PolicyDecision:
        if call.name in {"str_replace_edit", "write_file"}:
            path = call.args.get("path")
            if not path:
                return PolicyDecision.deny("Edit tool requires a path.", permission="filesystem")
            resolve_workspace_path(state, path, allow_run_artifacts=self.allow_run_artifacts)
            if _dirty_current_workspace(state):
                return PolicyDecision.needs_approval(
                    "edit would mutate a dirty current workspace",
                    _approval_request(call, state, action_kind="dirty_mutation", risk="medium"),
                    permission="filesystem",
                )
            return PolicyDecision.allow("edit path is inside workspace", permission="filesystem")
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
            return PolicyDecision.deny("Shell command is required.", matched_rule="shell.required", permission="bash")
        lower = cmd.lower()
        repeated = _repeated_failed_command_count(state, cmd)
        if repeated >= self.config.repeated_command_failure_limit:
            return PolicyDecision.deny(
                f"repeated identical failed command denied after {repeated} failures",
                matched_rule="bash.repeated_failed_command",
                permission="bash",
            )
        for pattern, reason in RISKY_SHELL_PATTERNS:
            if re.search(pattern, lower):
                return PolicyDecision.deny(reason, matched_rule=pattern, permission="bash")
        protected_write = _protected_tinyagent_write(cmd)
        if protected_write:
            return _decision_from_action(
                _resolve_permission(self.config, "contextfs_write", protected_write),
                call,
                state,
                reason=f"shell write to protected .tinyagent evidence is denied: {protected_write}",
                permission="contextfs_write",
                target=protected_write,
                action_kind="workspace_escape",
                risk="high",
                command=cmd,
            )
        env_access = _env_file_access(cmd)
        if env_access:
            return _decision_from_action(
                _resolve_permission(self.config, "secrets", env_access),
                call,
                state,
                reason=f"access to protected environment file is denied: {env_access}",
                permission="secrets",
                target=env_access,
                action_kind="workspace_escape",
                risk="high",
                command=cmd,
            )
        protected_output_write = _protected_output_write(cmd, state)
        if protected_output_write:
            return _decision_from_action(
                _resolve_permission(self.config, "run_artifact_write", protected_output_write),
                call,
                state,
                reason=f"shell write to protected run evidence is denied: {protected_output_write}",
                permission="run_artifact_write",
                target=protected_output_write,
                action_kind="workspace_escape",
                risk="high",
                command=cmd,
            )
        redirect_escape = _outside_redirect_target(cmd, state)
        if redirect_escape:
            return _decision_from_action(
                _resolve_permission(self.config, "external_directory", redirect_escape),
                call,
                state,
                reason=f"shell redirects outside workspace envelope: {redirect_escape}",
                permission="external_directory",
                target=redirect_escape,
                action_kind="workspace_escape",
                risk="high",
                command=cmd,
            )
        if _NETWORK_SHELL_PATTERN.search(lower):
            return _decision_from_action(
                _resolve_permission(self.config, "network", cmd),
                call,
                state,
                reason="network-looking shell command is denied by default",
                permission="network",
                target=cmd,
                action_kind="network",
                risk="high",
                command=cmd,
            )
        return _decision_from_action(
            _resolve_permission(self.config, "bash", cmd),
            call,
            state,
            reason="shell command passed local policy",
            permission="bash",
            target=cmd,
            action_kind="shell",
            risk="low",
            command=cmd,
        )


PolicyAction = Literal["allow", "ask", "deny"]


@dataclass(frozen=True)
class PolicyRule:
    permission: str
    pattern: str
    action: PolicyAction


@dataclass(frozen=True)
class PolicyConfig:
    default: PolicyAction = "deny"
    rules: tuple[PolicyRule, ...] = field(default_factory=tuple)
    repeated_command_failure_limit: int = 2


@dataclass(frozen=True)
class ResolvedPolicyRule:
    action: PolicyAction
    matched_rule: str


RISKY_SHELL_PATTERNS = (
    (r"\bsudo\b", "sudo is denied by default."),
    (r"\brm\b(?=[^;&|]*(?:-[^\s;&|]*r|--recursive))(?=[^;&|]*(?:-[^\s;&|]*f|--force))", "recursive force removal is denied by default."),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard is denied by default."),
    (r"\bgit\s+clean\s+-[^\n;&|]*f", "git clean -f is denied by default."),
    (r"\bgit\s+push\b", "git push is denied by default."),
    (r"\bmkfs\b", "filesystem formatting commands are denied by default."),
    (r"\bshutdown\b|\breboot\b", "machine power commands are denied by default."),
    (r":\(\)\s*\{\s*:\|:", "fork-bomb-like shell functions are denied by default."),
)

_NETWORK_SHELL_PATTERN = re.compile(r"\b(curl|wget|ssh|scp|sftp|rsync|nc|ncat|telnet)\b")
_REDIRECT_PATTERN = re.compile(r"(?:^|[\s;&|])(?:>|>>|<)\s*(?P<path>[^()\s;&|]+)")
_WRITE_REDIRECT_PATTERN = re.compile(r"(?:^|[\s;&|])(?:>|>>)\s*(?P<path>[^()\s;&|]+)")
_FILE_MUTATION_COMMANDS = frozenset({"tee", "mkdir", "touch", "rm", "mv", "cp"})
_TINYAGENT_WRITE_PATTERN = re.compile(
    r"(?:(?:>|>>)\s*(?P<redirect>(?:\./)?\.tinyagent(?:/|\b)[^\s;&|]*)|"
    r"\b(?:tee|mkdir|touch|rm|mv|cp)\b[^\n;&|]*(?P<command>(?:\./)?\.tinyagent(?:/|\b)[^\s;&|]*))"
)
_ENV_FILE_PATTERN = re.compile(
    r"(?P<path>(?:^|[\s'\"(=])(?:\./)?(?:[A-Za-z0-9_.-]+/)*\.env(?:\.[A-Za-z0-9_.-]+)?)(?:[\s'\"),]|$)"
)


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
        if raw == "/dev/null":
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = state.workspace.root / path
        envelope = state.workspace_envelope
        if envelope is not None:
            if not envelope.contains(path):
                return raw
        elif not state.workspace.contains(path):
            return raw
    return ""


def _protected_output_write(cmd: str, state: RunState) -> str:
    for raw in _write_targets(cmd):
        resolved = _resolve_shell_path(raw, state.workspace.root)
        if _is_protected_output_path(resolved, state):
            return raw
    return ""


def _write_targets(cmd: str) -> list[str]:
    targets = [match.group("path").strip("'\"") for match in _WRITE_REDIRECT_PATTERN.finditer(cmd)]
    words = _shell_words(cmd)
    if not words:
        return targets
    command_names = {Path(word).name for word in words if not word.startswith("-")}
    if command_names.isdisjoint(_FILE_MUTATION_COMMANDS):
        return targets
    targets.extend(word for word in words[1:] if not word.startswith("-"))
    return targets


def _resolve_shell_path(raw: str, cwd: Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def _is_protected_output_path(path: Path, state: RunState) -> bool:
    output_dir = state.output_dir.resolve()
    protected_dirs = (output_dir / "context", output_dir / "artifacts")
    protected_files = {
        output_dir / "events.jsonl",
        output_dir / "final.md",
        output_dir / "final.diff",
        output_dir / "metrics.json",
    }
    if any(_is_relative_to(path, root.resolve()) for root in protected_dirs):
        return True
    return path in {file.resolve() for file in protected_files}


def _protected_tinyagent_write(cmd: str) -> str:
    match = _TINYAGENT_WRITE_PATTERN.search(cmd)
    return (match.group("redirect") or match.group("command")) if match else ""


def _env_file_access(cmd: str) -> str:
    for word in _shell_words(cmd):
        normalized = word.strip("'\"")
        if _looks_like_env_path(normalized):
            return normalized
    match = _ENV_FILE_PATTERN.search(cmd)
    return match.group("path").strip(" '\"(=") if match else ""


def _shell_words(cmd: str) -> list[str]:
    try:
        return shlex.split(cmd)
    except ValueError:
        return cmd.split()


def _looks_like_env_path(value: str) -> bool:
    parts = Path(value).parts
    return any(part == ".env" or part.startswith(".env.") for part in parts)


def _resolve_permission(config: PolicyConfig, permission: str, target: str) -> ResolvedPolicyRule:
    action = config.default
    matched_rule = f"{permission}.default_{action}"
    for rule in config.rules:
        if rule.permission == permission and fnmatch(target, rule.pattern):
            action = rule.action
            matched_rule = f"{permission}:{rule.pattern}:{rule.action}"
    return ResolvedPolicyRule(action=action, matched_rule=matched_rule)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _decision_from_action(
    resolved: ResolvedPolicyRule,
    call: ToolCall,
    state: RunState,
    *,
    reason: str,
    permission: str,
    target: str,
    action_kind: str,
    risk: str,
    command: str | None = None,
) -> PolicyDecision:
    if resolved.action == "allow":
        return PolicyDecision.allow(reason, matched_rule=resolved.matched_rule, permission=permission)
    if resolved.action == "ask":
        return PolicyDecision.needs_approval(
            reason,
            _approval_request(call, state, action_kind=action_kind, risk=risk, args_preview=target, command=command),
            matched_rule=resolved.matched_rule,
            permission=permission,
        )
    return PolicyDecision.deny(reason, matched_rule=resolved.matched_rule, permission=permission)


def _repeated_failed_command_count(state: RunState, cmd: str) -> int:
    normalized = _normalize_command(cmd)
    count = 0
    for step in reversed(state.tool_steps):
        if step.call.name != "shell":
            continue
        if _normalize_command(str(step.call.args.get("cmd", ""))) != normalized:
            continue
        if step.result.ok:
            break
        count += 1
    return count


def _normalize_command(cmd: str) -> str:
    try:
        return " ".join(shlex.split(cmd))
    except ValueError:
        return " ".join(cmd.split())


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


def default_policy_config() -> PolicyConfig:
    return PolicyConfig(
        default="deny",
        rules=(
            PolicyRule("network", "*", "deny"),
            PolicyRule("contextfs_write", ".tinyagent/**", "deny"),
            PolicyRule("contextfs_write", "./.tinyagent/**", "deny"),
            PolicyRule("run_artifact_write", "*", "deny"),
            PolicyRule("secrets", ".env*", "deny"),
            PolicyRule("secrets", "./.env*", "deny"),
            PolicyRule("secrets", "*/.env*", "deny"),
            PolicyRule("external_directory", "*", "ask"),
            PolicyRule("bash", "git status*", "allow"),
            PolicyRule("bash", "git diff*", "allow"),
            PolicyRule("bash", "rg *", "allow"),
            PolicyRule("bash", "sed *", "allow"),
            PolicyRule("bash", "pytest *", "allow"),
            PolicyRule("bash", "uv run pytest*", "allow"),
            PolicyRule("bash", "npm test*", "allow"),
            PolicyRule("bash", "*", "allow"),
        ),
    )
