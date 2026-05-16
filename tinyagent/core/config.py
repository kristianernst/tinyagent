"""Run configuration metadata for eval variants."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RUN_CONFIG_KEYS = frozenset(
    {
        "provider",
        "model",
        "profile",
        "profile_variant",
        "context_policy",
        "tool_surface",
        "visible_tools",
        "workspace_mode",
        "approval_mode",
        "approvals_reviewer",
        "sandbox_mode",
        "context",
        "policy",
        "hooks",
        "budgets",
    }
)


@dataclass(frozen=True)
class RunConfig:
    provider: str = "fake"
    model: str = "fake"
    profile: str = "tiny-coder"
    profile_variant: str = "default"
    context_policy: str = "dynamic-v1"
    tool_surface: str = "default"
    visible_tools: tuple[str, ...] = ()
    workspace_mode: str = "current"
    approval_mode: str = "yolo"
    approvals_reviewer: str = "user"
    sandbox_mode: str = "none"
    context: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    hooks: tuple[str, ...] = ()
    budgets: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_path(cls, path: Path) -> RunConfig:
        data = tomllib.loads(path.read_text())
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunConfig:
        unknown = sorted(set(data) - RUN_CONFIG_KEYS)
        if unknown:
            raise ValueError(f"Unknown eval config fields: {', '.join(unknown)}")
        provider = str(data.get("provider") or "fake")
        model = str(data["model"]) if "model" in data else ("fake" if provider == "fake" else "")
        return cls(
            provider=provider,
            model=model,
            profile=str(data.get("profile") or "tiny-coder"),
            profile_variant=str(data.get("profile_variant") or "default"),
            context_policy=str(data.get("context_policy") or "dynamic-v1"),
            tool_surface=str(data.get("tool_surface") or "default"),
            visible_tools=_string_tuple(data, "visible_tools"),
            workspace_mode=str(data.get("workspace_mode") or "current"),
            approval_mode=str(data.get("approval_mode") or "yolo"),
            approvals_reviewer=str(data.get("approvals_reviewer") or "user"),
            sandbox_mode=str(data.get("sandbox_mode") or "none"),
            context=_dict_value(data, "context"),
            policy=_dict_value(data, "policy"),
            hooks=_string_tuple(data, "hooks"),
            budgets=_dict_value(data, "budgets"),
        )

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["visible_tools"] = list(self.visible_tools)
        data["hooks"] = list(self.hooks)
        return data

    def config_hash(self) -> str:
        payload = json.dumps(self.to_json_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _string_tuple(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key, ()) or ()
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{key} must be a list of strings")
    result = tuple(str(item) for item in value)
    if any(not item for item in result):
        raise ValueError(f"{key} must not contain empty strings")
    return result


def _dict_value(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {}) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a table")
    return dict(value)
