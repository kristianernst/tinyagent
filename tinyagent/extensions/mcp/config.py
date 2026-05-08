"""MCP config parsing."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from tinyagent.extensions.mcp.types import McpExposure, McpPermission, McpTransport


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    enabled: bool = True
    type: McpTransport = "stdio"
    command: tuple[str, ...] = ()
    url: str = ""
    env: dict[str, str] = field(default_factory=dict)
    timeout_seconds: int = 30
    exposure: McpExposure = "deferred"
    permission: McpPermission = "ask"
    tool_allowlist: tuple[str, ...] = ()
    tool_denylist: tuple[str, ...] = ()
    resource_allowlist: tuple[str, ...] = ()


@dataclass(frozen=True)
class McpConfig:
    servers: tuple[McpServerConfig, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> McpConfig:
        mcp = data.get("mcp") or {}
        if not isinstance(mcp, dict):
            raise ValueError("[mcp] must be a table")
        return cls(tuple(_server_config(name, value) for name, value in sorted(mcp.items())))

    def enabled_servers(self) -> tuple[McpServerConfig, ...]:
        return tuple(server for server in self.servers if server.enabled)

    def merge(self, other: McpConfig) -> McpConfig:
        merged = {server.name: server for server in self.servers}
        for server in other.servers:
            merged[server.name] = server
        return McpConfig(tuple(merged[name] for name in sorted(merged)))


def load_mcp_config(*paths: Path) -> McpConfig:
    config = McpConfig()
    for path in paths:
        if not path.exists():
            continue
        config = config.merge(McpConfig.from_dict(tomllib.loads(path.read_text())))
    return config


def _server_config(name: str, value: Any) -> McpServerConfig:
    if not isinstance(value, dict):
        raise ValueError(f"[mcp.{name}] must be a table")
    config = McpServerConfig(name=name)
    for key, raw in value.items():
        match key:
            case "enabled":
                config = replace(config, enabled=bool(raw))
            case "type":
                config = replace(config, type=_one_of(raw, {"stdio", "http", "sse", "streamable_http"}, key))
            case "command":
                config = replace(config, command=_string_tuple(raw, key))
            case "url":
                config = replace(config, url=str(raw))
            case "env":
                config = replace(config, env=_string_dict(raw, key))
            case "timeout_seconds":
                config = replace(config, timeout_seconds=max(int(raw), 1))
            case "exposure":
                config = replace(config, exposure=_one_of(raw, {"hidden", "deferred", "direct"}, key))
            case "permission":
                config = replace(config, permission=_one_of(raw, {"allow", "ask", "deny"}, key))
            case "tool_allowlist":
                config = replace(config, tool_allowlist=_string_tuple(raw, key))
            case "tool_denylist":
                config = replace(config, tool_denylist=_string_tuple(raw, key))
            case "resource_allowlist":
                config = replace(config, resource_allowlist=_string_tuple(raw, key))
            case _:
                raise ValueError(f"Unknown MCP config field: mcp.{name}.{key}")
    if config.type == "stdio" and not config.command:
        raise ValueError(f"mcp.{name}.command is required for stdio MCP")
    if config.type != "stdio" and not config.url:
        raise ValueError(f"mcp.{name}.url is required for remote MCP")
    return config


def _one_of(value: Any, allowed: set[str], key: str) -> Any:
    text = str(value)
    if text not in allowed:
        raise ValueError(f"{key} must be one of: {', '.join(sorted(allowed))}")
    return text


def _string_tuple(value: Any, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be a list of strings")
    return tuple(value)


def _string_dict(value: Any, key: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise ValueError(f"{key} must be a string map")
    return dict(value)
