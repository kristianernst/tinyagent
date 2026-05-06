"""Run configuration metadata for eval variants."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

VARIANT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
RUN_CONFIG_KEYS = frozenset(
    {
        "provider",
        "model",
        "profile",
        "visible_tools",
        "workspace_mode",
        "approval_mode",
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
    visible_tools: tuple[str, ...] = ()
    workspace_mode: str = "current"
    approval_mode: str = "yolo"
    sandbox_mode: str = "none"
    context: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
    hooks: tuple[str, ...] = ()
    budgets: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_path(cls, path: Path) -> "RunConfig":
        data = tomllib.loads(path.read_text())
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunConfig":
        unknown = sorted(set(data) - RUN_CONFIG_KEYS)
        if unknown:
            raise ValueError(f"Unknown eval config fields: {', '.join(unknown)}")
        provider = str(data.get("provider") or "fake")
        model = str(data["model"]) if "model" in data else ("fake" if provider == "fake" else "")
        return cls(
            provider=provider,
            model=model,
            profile=str(data.get("profile") or "tiny-coder"),
            visible_tools=_string_tuple(data, "visible_tools"),
            workspace_mode=str(data.get("workspace_mode") or "current"),
            approval_mode=str(data.get("approval_mode") or "yolo"),
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

    def validate_supported_eval_compare(self) -> None:
        if self.provider not in {"fake", "openai-compatible"}:
            raise ValueError(f"Unsupported eval provider: {self.provider}")
        if self.profile != "tiny-coder":
            raise ValueError(f"Unsupported eval profile: {self.profile}")
        if self.workspace_mode not in {"auto", "current", "worktree"}:
            raise ValueError(f"Unsupported workspace_mode: {self.workspace_mode}")
        if self.approval_mode not in {"never", "on-request", "yolo"}:
            raise ValueError(f"Unsupported approval_mode: {self.approval_mode}")
        if self.approval_mode == "on-request":
            raise ValueError("approval_mode=on-request is not supported for eval compare")
        if self.sandbox_mode not in {"none", "container", "native"}:
            raise ValueError(f"Unsupported sandbox_mode: {self.sandbox_mode}")
        unsupported = []
        if self.context:
            unsupported.append("context")
        if self.policy:
            unsupported.append("policy")
        if self.hooks:
            unsupported.append("hooks")
        if self.budgets:
            unsupported.append("budgets")
        if unsupported:
            raise ValueError(f"Unsupported eval config fields: {', '.join(unsupported)}")

    def config_hash(self) -> str:
        payload = json.dumps(self.to_json_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class VariantSpec:
    name: str
    config: RunConfig = field(default_factory=RunConfig)
    config_path: str = ""

    @classmethod
    def parse(cls, value: str) -> "VariantSpec":
        if "=" not in value:
            name = value
            _validate_variant_name(name)
            return cls(name=name)
        name, raw_path = value.split("=", 1)
        _validate_variant_name(name)
        path = Path(raw_path).expanduser().resolve()
        return cls(name=name, config=RunConfig.from_path(path), config_path=str(path))

    def metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "config_path": self.config_path,
            "config_file_hash": _file_hash(self.config_path),
            "config_hash": self.config.config_hash(),
            "git_sha": _git(["rev-parse", "HEAD"]),
            "branch": _git(["branch", "--show-current"]),
            "git_dirty": bool(_git(["status", "--porcelain=v1"])),
            "git_diff_hash": _git_diff_hash(),
            "git_untracked_hash": _git_untracked_hash(),
            "config": self.config.to_json_dict(),
        }


def _git(args: list[str]) -> str:
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_bytes(args: list[str]) -> bytes:
    try:
        result = subprocess.run(["git", *args], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return b""
    return result.stdout if result.returncode == 0 else b""


def _git_diff_hash() -> str:
    data = _git_bytes(["diff", "--binary", "HEAD", "--"])
    return hashlib.sha256(data).hexdigest()[:12] if data else ""


def _git_untracked_hash() -> str:
    raw = _git_bytes(["ls-files", "--others", "--exclude-standard", "-z"])
    if not raw:
        return ""
    hasher = hashlib.sha256()
    for item in raw.split(b"\0"):
        if not item:
            continue
        path = Path(item.decode(errors="surrogateescape"))
        hasher.update(path.as_posix().encode())
        hasher.update(b"\0")
        try:
            if path.is_file():
                hasher.update(path.read_bytes())
        except OSError:
            pass
        hasher.update(b"\0")
    return hasher.hexdigest()[:12]


def _file_hash(path: str) -> str:
    if not path:
        return ""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()[:12]


def _validate_variant_name(name: str) -> None:
    if not VARIANT_NAME_PATTERN.fullmatch(name):
        raise ValueError("Variant names must start with a letter or digit and contain only letters, digits, dots, underscores, and hyphens.")


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
