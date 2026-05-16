"""Default local policy for bounded workspace execution."""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterable
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal

from tinyagent.core.contracts import PolicyEngine
from tinyagent.core.index.safety import parse_code_ref
from tinyagent.core.path_safety import looks_like_env_path, resolved_relative_to
from tinyagent.core.state import ApprovalRequest, PolicyDecision, RunState, ToolCall
from tinyagent.core.tools import patch_paths, resolve_workspace_path


class LocalPolicy:
    """Classifier-first local policy for bounded workspace bash.

    This is not a sandbox. Network, secrets, ContextFS/evidence writes,
    external redirects, repeated failures, and known destructive commands are
    restricted before read-only and verification commands are allowed. Unknown
    shell commands ask by default.
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
                case "search_code":
                    resolve_workspace_path(state, call.args.get("path", "."), allow_run_artifacts=False)
                    return PolicyDecision.allow("search_code path is inside workspace", permission="workspace_index")
                case "context_search":
                    source = str(call.args.get("source") or "*")
                    for permission, target, reason, risk in _context_search_checks(source):
                        decision = self._decision(call, state, permission, target, reason=reason, risk=risk)
                        if not decision.allowed:
                            return decision
                    return self._decision(call, state, "context_search", source, reason="dynamic context search")
                case "context_read":
                    ref = str(call.args.get("ref") or "*")
                    if ref.startswith("workspace_index:"):
                        code_ref = ref.removeprefix("workspace_index:")
                        if not code_ref.startswith("code:"):
                            return PolicyDecision.deny(f"Unsupported workspace index ref: {ref}", permission="context_read")
                        path_part, _line = parse_code_ref(code_ref)
                        resolve_workspace_path(state, path_part, allow_run_artifacts=False)
                    for permission, target, reason, risk in _context_read_checks(ref):
                        decision = self._decision(call, state, permission, target, reason=reason, risk=risk)
                        if not decision.allowed:
                            return decision
                    return self._decision(call, state, "context_read", ref, reason="dynamic context read")
                case "list_skills":
                    return self._decision(call, state, "skill", "list", reason="skill catalogue read")
                case "load_skill":
                    target = str(call.args.get("name_or_id") or "*")
                    return self._decision(call, state, "skill", target, reason="skill instruction read")
                case "mcp_search_tools" | "mcp_load_tool":
                    server = str(call.args.get("server") or "*") or "*"
                    decision = self._decision(call, state, "mcp_server", server, reason="MCP catalogue access")
                    return _network_guard_if_allowed(self.config, decision, call, state, target=f"mcp:{server}")
                case "mcp_call":
                    server = str(call.args.get("server") or "*") or "*"
                    tool = str(call.args.get("tool") or "*") or "*"
                    decision = self._decision(
                        call,
                        state,
                        "mcp_tool",
                        f"{server}.{tool}",
                        reason="MCP tool call",
                        action_kind="network",
                        risk="medium",
                    )
                    return _network_guard_if_allowed(self.config, decision, call, state, target=f"mcp:{server}")
                case "mcp_read_resource":
                    server = str(call.args.get("server") or "*") or "*"
                    uri = str(call.args.get("uri") or "*") or "*"
                    decision = self._decision(
                        call,
                        state,
                        "mcp_resource",
                        f"{server}:{uri}",
                        reason="MCP resource read",
                        action_kind="network",
                        risk="medium",
                    )
                    return _network_guard_if_allowed(self.config, decision, call, state, target=f"mcp:{server}")
                case "lsp_symbols" | "lsp_definition" | "lsp_references" | "lsp_diagnostics":
                    path = str(call.args.get("path") or "*") or "*"
                    if path != "*":
                        resolve_workspace_path(state, path, allow_run_artifacts=False)
                    return self._decision(call, state, "lsp", path, reason="LSP code-intelligence query")
                case "todo_read" | "todo_write":
                    return self._decision(call, state, "working_memory", "run", reason="run-scoped working memory access")
                case "apply_patch" | "str_replace_edit" | "write_file":
                    return self._evaluate_patch(call, state)
                case "shell":
                    return self._evaluate_shell(call, state)
        except Exception as exc:
            return PolicyDecision.deny(str(exc))
        return PolicyDecision.deny(f"Unknown tool for policy: {call.name}")

    def _decision(
        self,
        call: ToolCall,
        state: RunState,
        permission: str,
        target: str,
        *,
        reason: str,
        action_kind: str = "unknown",
        risk: str = "low",
        command: str | None = None,
    ) -> PolicyDecision:
        return _decision_from_action(
            _resolve_permission(self.config, permission, target),
            call,
            state,
            reason=reason,
            permission=permission,
            target=target,
            action_kind=action_kind,
            risk=risk,
            command=command,
        )

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
            return self._decision(
                call,
                state,
                "contextfs_write",
                protected_write,
                reason=f"shell write to protected .tinyagent evidence is denied: {protected_write}",
                action_kind="workspace_escape",
                risk="high",
                command=cmd,
            )
        env_access = _env_file_access(cmd)
        if env_access:
            return self._decision(
                call,
                state,
                "secrets",
                env_access,
                reason=f"access to protected environment file is denied: {env_access}",
                action_kind="workspace_escape",
                risk="high",
                command=cmd,
            )
        protected_output_write = _protected_output_write(cmd, state)
        if protected_output_write:
            return self._decision(
                call,
                state,
                "run_artifact_write",
                protected_output_write,
                reason=f"shell write to protected run evidence is denied: {protected_output_write}",
                action_kind="workspace_escape",
                risk="high",
                command=cmd,
            )
        redirect_escape = _outside_redirect_target(cmd, state)
        if redirect_escape:
            return self._decision(
                call,
                state,
                "external_directory",
                redirect_escape,
                reason=f"shell redirects outside workspace envelope: {redirect_escape}",
                action_kind="workspace_escape",
                risk="high",
                command=cmd,
            )
        workspace_write = _workspace_write_target(cmd, state)
        if workspace_write:
            return PolicyDecision.needs_approval(
                f"shell command may write to workspace: {workspace_write}",
                _approval_request(call, state, action_kind="shell", risk="medium", args_preview=cmd, command=cmd),
                matched_rule="bash.workspace_write",
                permission="bash",
            )
        read_only_mutation = _read_only_command_mutation(cmd)
        if read_only_mutation:
            return PolicyDecision.needs_approval(
                f"read-only shell allowlist used with mutating option: {read_only_mutation}",
                _approval_request(call, state, action_kind="shell", risk="medium", args_preview=cmd, command=cmd),
                matched_rule="bash.read_only_mutation",
                permission="bash",
            )
        outside_read = _outside_read_target(cmd, state, allow_run_artifacts=self.allow_run_artifacts)
        if outside_read:
            return self._decision(
                call,
                state,
                "external_directory",
                outside_read,
                reason=f"shell reads outside workspace envelope: {outside_read}",
                action_kind="workspace_escape",
                risk="high",
                command=cmd,
            )
        if _NETWORK_SHELL_PATTERN.search(lower):
            return self._decision(
                call,
                state,
                "network",
                cmd,
                reason="network-looking shell command is denied by default",
                action_kind="network",
                risk="high",
                command=cmd,
            )
        if _safe_find_listing(cmd, state):
            return PolicyDecision.allow(
                "read-only find listing is inside workspace",
                matched_rule="bash.find.safe_listing",
                permission="bash",
            )
        return self._decision(
            call,
            state,
            "bash",
            cmd,
            reason="shell command passed local policy",
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
_SIMPLE_READ_COMMANDS = frozenset({"cat", "head", "tail", "wc", "ls"})
_FIND_MUTATING_TOKENS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fls"})
_RG_VALUE_FLAGS = frozenset(
    {
        "-A",
        "-B",
        "-C",
        "-E",
        "-g",
        "-j",
        "-m",
        "-t",
        "-T",
        "--after-context",
        "--before-context",
        "--color",
        "--colors",
        "--context",
        "--encoding",
        "--glob",
        "--max-count",
        "--path-separator",
        "--pre",
        "--sort",
        "--sortr",
        "--threads",
        "--type",
        "--type-not",
    }
)
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


def _workspace_write_target(cmd: str, state: RunState) -> str:
    for raw in _write_targets(cmd):
        resolved = _resolve_shell_path(raw, state.workspace.root)
        if state.workspace.contains(resolved):
            return raw
        envelope = state.workspace_envelope
        if envelope is not None and envelope.contains(resolved):
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
    if any(resolved_relative_to(path, root) is not None for root in protected_dirs):
        return True
    return path in {file.resolve() for file in protected_files}


def _read_only_command_mutation(cmd: str) -> str:
    words = _shell_words(cmd)
    if not words:
        return ""
    command = Path(words[0]).name
    if command == "sed" and any(word == "-i" or word.startswith("-i") for word in words[1:]):
        return "sed -i"
    if command == "git" and len(words) > 2 and words[1] == "diff" and any(
        word == "--output" or word.startswith("--output=") for word in words[2:]
    ):
        return "git diff --output"
    return ""


def _outside_read_target(cmd: str, state: RunState, *, allow_run_artifacts: bool) -> str:
    for raw in _read_targets(cmd):
        if raw == "-":
            continue
        try:
            resolve_workspace_path(state, raw, allow_run_artifacts=allow_run_artifacts)
        except Exception:
            return raw
    return ""


def _read_targets(cmd: str) -> list[str]:
    words = _shell_words(cmd)
    if not words:
        return []
    command = Path(words[0]).name
    if command in _SIMPLE_READ_COMMANDS:
        return _plain_path_operands(words[1:])
    if command == "sed":
        return _sed_path_operands(words[1:])
    if command == "rg":
        return _rg_path_operands(words[1:])
    if command == "git" and len(words) > 2 and words[1] == "diff" and "--no-index" in words[2:]:
        return _plain_path_operands(word for word in words[2:] if word != "--no-index")
    return []


def _safe_find_listing(cmd: str, state: RunState) -> bool:
    words = _shell_words(cmd)
    if not words or Path(words[0]).name != "find":
        return False
    if "&&" in words or "||" in words or ";" in cmd:
        return False
    pipe_indexes = [index for index, word in enumerate(words) if word == "|"]
    if len(pipe_indexes) > 1:
        return False
    pipe_index = pipe_indexes[0] if pipe_indexes else len(words)
    find_words = words[1:pipe_index]
    if not find_words:
        find_words = ["."]
    if any(word in _FIND_MUTATING_TOKENS or word.startswith(("-exec", "-ok")) for word in find_words):
        return False
    if pipe_indexes and not _safe_find_pipe_tail(words[pipe_index + 1 :]):
        return False
    path_operands = _find_path_operands(find_words)
    for raw in path_operands or ["."]:
        resolved = _resolve_shell_path(raw, state.workspace.root)
        envelope = state.workspace_envelope
        if envelope is not None:
            if not envelope.contains(resolved):
                return False
        elif not state.workspace.contains(resolved):
            return False
    return True


def _safe_find_pipe_tail(words: list[str]) -> bool:
    if not words:
        return False
    command = Path(words[0]).name
    if command == "head":
        return all(word.startswith("-") or word.isdigit() for word in words[1:])
    if command == "sort":
        return not any(word == "-o" or word.startswith("--output") for word in words[1:])
    return False


def _find_path_operands(words: list[str]) -> list[str]:
    paths: list[str] = []
    expression_started = False
    for word in words:
        if word == "--":
            expression_started = False
            continue
        if word in {"!", "(", ")"} or word.startswith("-"):
            expression_started = True
            continue
        if not expression_started:
            paths.append(word)
            continue
        if not paths:
            paths.append(".")
    return paths


def _plain_path_operands(words: Iterable[str]) -> list[str]:
    operands: list[str] = []
    take_rest = False
    for word in words:
        if word == "--":
            take_rest = True
            continue
        if not take_rest and word.startswith("-"):
            continue
        if word in {"|", ";", "&&", "||"}:
            continue
        operands.append(word)
    return operands


def _sed_path_operands(words: list[str]) -> list[str]:
    operands: list[str] = []
    script_seen = False
    index = 0
    while index < len(words):
        word = words[index]
        if word in {"-e", "--expression"}:
            script_seen = True
            index += 2
            continue
        if word.startswith("--expression=") or (word.startswith("-e") and word != "-e"):
            script_seen = True
            index += 1
            continue
        if word in {"-f", "--file"}:
            if index + 1 < len(words):
                operands.append(words[index + 1])
                script_seen = True
            index += 2
            continue
        if word.startswith("--file="):
            operands.append(word.split("=", 1)[1])
            script_seen = True
            index += 1
            continue
        if word.startswith("-"):
            index += 1
            continue
        if not script_seen:
            script_seen = True
        else:
            operands.append(word)
        index += 1
    return operands


def _rg_path_operands(words: list[str]) -> list[str]:
    operands: list[str] = []
    pattern_seen = any(word == "--files" for word in words)
    index = 0
    while index < len(words):
        word = words[index]
        if word == "--":
            operands.extend(words[index + 1 :] if pattern_seen else words[index + 2 :])
            break
        if word in {"-e", "--regexp"}:
            pattern_seen = True
            index += 2
            continue
        if word in {"-f", "--file"}:
            if index + 1 < len(words):
                operands.append(words[index + 1])
                pattern_seen = True
            index += 2
            continue
        if word.startswith("--regexp="):
            pattern_seen = True
            index += 1
            continue
        if word.startswith("--file="):
            operands.append(word.split("=", 1)[1])
            pattern_seen = True
            index += 1
            continue
        if word in _RG_VALUE_FLAGS:
            index += 2
            continue
        if any(word.startswith(f"{flag}=") for flag in _RG_VALUE_FLAGS if flag.startswith("--")):
            index += 1
            continue
        if word.startswith("-"):
            index += 1
            continue
        if pattern_seen:
            operands.append(word)
        else:
            pattern_seen = True
        index += 1
    return operands


def _protected_tinyagent_write(cmd: str) -> str:
    match = _TINYAGENT_WRITE_PATTERN.search(cmd)
    return (match.group("redirect") or match.group("command")) if match else ""


def _env_file_access(cmd: str) -> str:
    for word in _shell_words(cmd):
        normalized = word.strip("'\"")
        if looks_like_env_path(normalized):
            return normalized
    match = _ENV_FILE_PATTERN.search(cmd)
    return match.group("path").strip(" '\"(=") if match else ""


def _shell_words(cmd: str) -> list[str]:
    try:
        return shlex.split(cmd)
    except ValueError:
        return cmd.split()


def _mcp_server_from_context_ref(ref: str) -> str:
    local = ref.removeprefix("mcp_tools:")
    if local.startswith("mcp-tool:"):
        return local.removeprefix("mcp-tool:").split("/", 1)[0] or "*"
    if local.startswith("mcp-resource:"):
        return local.removeprefix("mcp-resource:").split("/", 1)[0] or "*"
    return "*"


PolicyCheck = tuple[str, str, str, str]


def _context_search_checks(source: str) -> tuple[PolicyCheck, ...]:
    checks: list[PolicyCheck] = []
    if source in {"*", "skills"}:
        checks.append(("skill", "list", "skill catalogue search through dynamic context", "low"))
    if source in {"*", "memory"}:
        checks.append(("working_memory", "run", "working memory search through dynamic context", "low"))
    if source in {"*", "memory"}:
        checks.append(("working_memory", "files", "file-backed memory search through dynamic context", "low"))
    if source == "mcp_tools":
        checks.append(("mcp_server", "*", "MCP catalogue search through dynamic context", "medium"))
    if source in {"*", "lsp_symbols"}:
        checks.append(("lsp", "*", "LSP symbol search through dynamic context", "low"))
    return tuple(checks)


def _context_read_checks(ref: str) -> tuple[PolicyCheck, ...]:
    if ref.startswith("skills:"):
        target = ref.removeprefix("skills:").split("/", 1)[0] or "*"
        return (("skill", target, "skill instruction read through dynamic context", "low"),)
    if ref.startswith("mcp_tools:"):
        return (("mcp_server", _mcp_server_from_context_ref(ref), "MCP catalogue read through dynamic context", "medium"),)
    if ref.startswith("memory:"):
        target = ref.removeprefix("memory:").split("/", 1)[0] or "*"
        if target in {"todo", "todo/current"}:
            return (("working_memory", "run", "working memory read through dynamic context", "low"),)
        return (("working_memory", "files", "file-backed memory read through dynamic context", "low"),)
    if ref.startswith("lsp_symbols:"):
        return (("lsp", "*", "LSP symbol read through dynamic context", "low"),)
    return ()


def _network_guard_if_allowed(
    config: PolicyConfig,
    decision: PolicyDecision,
    call: ToolCall,
    state: RunState,
    *,
    target: str,
) -> PolicyDecision:
    if not decision.allowed:
        return decision
    network = _decision_from_action(
        _resolve_permission(config, "network", target),
        call,
        state,
        reason="MCP access also requires network permission",
        permission="network",
        target=target,
        action_kind="network",
        risk="medium",
    )
    return network if not network.allowed else decision


def _resolve_permission(config: PolicyConfig, permission: str, target: str) -> ResolvedPolicyRule:
    action = config.default
    matched_rule = f"{permission}.default_{action}"
    for rule in config.rules:
        if rule.permission == permission and fnmatch(target, rule.pattern):
            action = rule.action
            matched_rule = f"{permission}:{rule.pattern}:{rule.action}"
    return ResolvedPolicyRule(action=action, matched_rule=matched_rule)


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
            PolicyRule("context_search", "*", "allow"),
            PolicyRule("context_read", "contextfs:*", "allow"),
            PolicyRule("context_read", "conversation:*", "allow"),
            PolicyRule("context_read", "past_runs:*", "allow"),
            PolicyRule("context_read", "skills:*", "allow"),
            PolicyRule("context_read", "workspace_index:*", "allow"),
            PolicyRule("context_read", "mcp_tools:*", "allow"),
            PolicyRule("context_read", "memory:*", "allow"),
            PolicyRule("context_read", "lsp_symbols:*", "allow"),
            PolicyRule("skill", "*", "allow"),
            PolicyRule("mcp_server", "*", "ask"),
            PolicyRule("mcp_tool", "*", "ask"),
            PolicyRule("mcp_resource", "*", "ask"),
            PolicyRule("lsp", "*", "ask"),
            PolicyRule("working_memory", "run", "allow"),
            PolicyRule("working_memory", "files", "allow"),
            PolicyRule("bash", "*", "ask"),
            PolicyRule("bash", "git status*", "allow"),
            PolicyRule("bash", "git diff*", "allow"),
            PolicyRule("bash", "git log*", "allow"),
            PolicyRule("bash", "git show*", "allow"),
            PolicyRule("bash", "ls*", "allow"),
            PolicyRule("bash", "pwd", "allow"),
            PolicyRule("bash", "rg *", "allow"),
            PolicyRule("bash", "sed *", "allow"),
            PolicyRule("bash", "cat *", "allow"),
            PolicyRule("bash", "head *", "allow"),
            PolicyRule("bash", "tail *", "allow"),
            PolicyRule("bash", "wc *", "allow"),
            PolicyRule("bash", "pytest", "allow"),
            PolicyRule("bash", "pytest *", "allow"),
            PolicyRule("bash", "python3 -m unittest*", "allow"),
            PolicyRule("bash", "python -m unittest*", "allow"),
            PolicyRule("bash", "python3 scripts/validate.py", "allow"),
            PolicyRule("bash", "python3 scripts/validate.py *", "allow"),
            PolicyRule("bash", "python3 ./scripts/validate.py", "allow"),
            PolicyRule("bash", "python3 ./scripts/validate.py *", "allow"),
            PolicyRule("bash", "python scripts/validate.py", "allow"),
            PolicyRule("bash", "python scripts/validate.py *", "allow"),
            PolicyRule("bash", "python ./scripts/validate.py", "allow"),
            PolicyRule("bash", "python ./scripts/validate.py *", "allow"),
            PolicyRule("bash", "uv run pytest", "allow"),
            PolicyRule("bash", "uv run pytest*", "allow"),
            PolicyRule("bash", "npm test", "allow"),
            PolicyRule("bash", "npm test*", "allow"),
        ),
    )
