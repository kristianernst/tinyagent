"""MCP extension data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

McpExposure = Literal["hidden", "deferred", "direct"]
McpPermission = Literal["allow", "ask", "deny"]
McpTransport = Literal["stdio", "http", "sse", "streamable_http"]


@dataclass(frozen=True)
class McpToolInfo:
    server: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    auth: str = "ready"
    permission: McpPermission = "ask"
    mutating: bool = False
    exposure: McpExposure = "deferred"

    @property
    def qualified_name(self) -> str:
        return f"{self.server}.{self.name}"


@dataclass(frozen=True)
class McpResourceInfo:
    server: str
    uri: str
    name: str = ""
    description: str = ""
    auth: str = "ready"
    permission: McpPermission = "ask"


@dataclass(frozen=True)
class McpResult:
    content: str
    structured_content: dict[str, Any] | list[Any] | None = None
    title: str = ""
