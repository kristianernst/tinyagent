"""Eval variant parsing and support validation."""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tinyagent.core.config import RunConfig
from tinyagent.core.providers.factory import DEFAULT_PROVIDER_REGISTRY

VARIANT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class VariantSpec:
    name: str
    config: RunConfig = field(default_factory=RunConfig)
    config_path: str = ""

    @classmethod
    def parse(cls, value: str) -> VariantSpec:
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


def validate_supported_eval_compare(config: RunConfig) -> None:
    if config.provider not in DEFAULT_PROVIDER_REGISTRY.kinds():
        raise ValueError(f"Unsupported eval provider: {config.provider}")
    if config.profile not in {"tiny-coder", "tiny-pi"}:
        raise ValueError(f"Unsupported eval profile: {config.profile}")
    expected = {
        "tiny-coder": ("default", "dynamic-v1", "default"),
        "tiny-pi": ("minimal", "pi-v1", "pi-minimal"),
    }[config.profile]
    if config.profile_variant != expected[0]:
        raise ValueError(f"Unsupported eval profile_variant: {config.profile_variant}")
    if config.context_policy != expected[1]:
        raise ValueError(f"Unsupported eval context_policy: {config.context_policy}")
    if config.tool_surface != expected[2]:
        raise ValueError(f"Unsupported eval tool_surface: {config.tool_surface}")
    if config.workspace_mode not in {"auto", "current", "worktree"}:
        raise ValueError(f"Unsupported workspace_mode: {config.workspace_mode}")
    if config.approval_mode not in {"never", "on-request", "yolo"}:
        raise ValueError(f"Unsupported approval_mode: {config.approval_mode}")
    if config.approval_mode == "on-request":
        raise ValueError("approval_mode=on-request is not supported for eval compare")
    if config.sandbox_mode not in {"none", "container", "native"}:
        raise ValueError(f"Unsupported sandbox_mode: {config.sandbox_mode}")
    unsupported = []
    if config.context:
        unsupported.append("context")
    if config.policy:
        unsupported.append("policy")
    if config.hooks:
        unsupported.append("hooks")
    if config.budgets:
        unsupported.append("budgets")
    if unsupported:
        raise ValueError(f"Unsupported eval config fields: {', '.join(unsupported)}")


def _validate_variant_name(name: str) -> None:
    if not VARIANT_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            "Variant names must start with a letter or digit and contain only letters, digits, dots, underscores, and hyphens."
        )


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
