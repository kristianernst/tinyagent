"""Named permission profile presets for local runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from tinyagent.core.contracts import PolicyEngine
from tinyagent.core.policy import LocalPolicy, PolicyConfig, PolicyRule, default_policy_config
from tinyagent.core.state import ApprovalMode
from tinyagent.core.workspace import SandboxModeInput, WorkspaceMode


PermissionProfileName = Literal["read-only", "workspace-write", "contained-yolo", "danger-full-access"]
PERMISSION_PROFILE_NAMES: tuple[PermissionProfileName, ...] = (
    "read-only",
    "workspace-write",
    "contained-yolo",
    "danger-full-access",
)


@dataclass(frozen=True)
class PermissionProfile:
    name: PermissionProfileName
    workspace_mode: WorkspaceMode
    approval_mode: ApprovalMode
    sandbox_mode: SandboxModeInput
    policy_config: PolicyConfig
    enforce_policy_in_yolo: bool = False
    deny_yolo_approvals: bool = False

    def policy(self) -> PolicyEngine:
        return LocalPolicy(config=self.policy_config)


def permission_profile_for(name: str | None) -> PermissionProfile | None:
    if name is None:
        return None
    match name:
        case "read-only":
            return PermissionProfile(
                name="read-only",
                workspace_mode="current",
                approval_mode="never",
                sandbox_mode="none",
                policy_config=_with_rules(PolicyRule("filesystem", "*", "deny")),
                enforce_policy_in_yolo=True,
                deny_yolo_approvals=True,
            )
        case "workspace-write":
            return PermissionProfile(
                name="workspace-write",
                workspace_mode="auto",
                approval_mode="on-request",
                sandbox_mode="none",
                policy_config=default_policy_config(),
            )
        case "contained-yolo":
            return PermissionProfile(
                name="contained-yolo",
                workspace_mode="worktree",
                approval_mode="yolo",
                sandbox_mode="container",
                policy_config=default_policy_config(),
                enforce_policy_in_yolo=True,
            )
        case "danger-full-access":
            return PermissionProfile(
                name="danger-full-access",
                workspace_mode="current",
                approval_mode="yolo",
                sandbox_mode="none",
                policy_config=_with_rules(
                    PolicyRule("network", "*", "allow"),
                    PolicyRule("external_directory", "*", "allow"),
                    PolicyRule("filesystem", "*", "allow"),
                    PolicyRule("bash", "*", "allow"),
                ),
                enforce_policy_in_yolo=True,
            )
    raise ValueError(f"Unknown permission profile: {name}")


def policy_for_permission_profile(name: str | None) -> PolicyEngine:
    profile = permission_profile_for(name)
    return profile.policy() if profile is not None else LocalPolicy()


def _with_rules(*overrides: PolicyRule) -> PolicyConfig:
    base = default_policy_config()
    return PolicyConfig(
        default=base.default,
        rules=(*base.rules, *overrides),
        repeated_command_failure_limit=base.repeated_command_failure_limit,
    )
