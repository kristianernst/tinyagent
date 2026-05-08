"""LSP extension config types."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LspServerConfig:
    name: str
    command: tuple[str, ...]
    extensions: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)
    initialization: dict[str, Any] = field(default_factory=dict)
    disabled: bool = False
    permission: str = "ask"


@dataclass(frozen=True)
class LspConfig:
    enabled: bool = False
    servers: tuple[LspServerConfig, ...] = ()
    configured: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LspConfig:
        extensions = data.get("extensions") or {}
        if not isinstance(extensions, dict):
            raise ValueError("[extensions] must be a table")
        raw_lsp = extensions.get("lsp") or {}
        if not isinstance(raw_lsp, dict):
            raise ValueError("[extensions.lsp] must be a table")
        servers = raw_lsp.get("servers") or {}
        if not isinstance(servers, dict):
            raise ValueError("[extensions.lsp.servers] must be a table")
        return cls(
            enabled=bool(raw_lsp.get("enabled", False)),
            servers=tuple(_server_config(name, value) for name, value in sorted(servers.items())),
            configured="lsp" in extensions,
        )

    def merge(self, other: LspConfig) -> LspConfig:
        servers = {server.name: server for server in self.servers}
        for server in other.servers:
            servers[server.name] = server
        enabled = other.enabled if other.configured else self.enabled
        return LspConfig(
            enabled=enabled,
            servers=tuple(servers[name] for name in sorted(servers)),
            configured=self.configured or other.configured,
        )


def load_lsp_config(*paths: Path) -> LspConfig:
    config = LspConfig()
    for path in paths:
        if not path.exists():
            continue
        config = config.merge(LspConfig.from_dict(tomllib.loads(path.read_text())))
    return config


def _server_config(name: str, value: Any) -> LspServerConfig:
    if not isinstance(value, dict):
        raise ValueError(f"[extensions.lsp.servers.{name}] must be a table")
    command = _string_tuple(value.get("command") or (), "command")
    extensions = _string_tuple(value.get("extensions") or (), "extensions")
    if not command:
        raise ValueError(f"extensions.lsp.servers.{name}.command is required")
    if not extensions:
        raise ValueError(f"extensions.lsp.servers.{name}.extensions is required")
    return LspServerConfig(
        name=name,
        command=command,
        extensions=extensions,
        env=_string_dict(value.get("env") or {}, "env"),
        initialization=dict(value.get("initialization") or {}),
        disabled=bool(value.get("disabled", False)),
        permission=str(value.get("permission") or "ask"),
    )


def _string_tuple(value: Any, key: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return tuple(value)


def _string_dict(value: Any, key: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ValueError(f"{key} must be a string map")
    return dict(value)
