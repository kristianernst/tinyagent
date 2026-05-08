"""MCP client protocol and test client."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from tinyagent.extensions.mcp.types import McpResourceInfo, McpResult, McpToolInfo


class McpClient(Protocol):
    def list_tools(self) -> list[McpToolInfo]: ...

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> McpResult: ...

    def list_resources(self) -> list[McpResourceInfo]: ...

    def read_resource(self, uri: str) -> McpResult: ...


class InMemoryMcpClient:
    def __init__(
        self,
        *,
        tools: list[McpToolInfo] | None = None,
        resources: list[McpResourceInfo] | None = None,
        tool_results: Mapping[str, McpResult] | None = None,
        resource_results: Mapping[str, McpResult] | None = None,
    ) -> None:
        self._tools = tuple(tools or ())
        self._resources = tuple(resources or ())
        self._tool_results = dict(tool_results or {})
        self._resource_results = dict(resource_results or {})
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_tools(self) -> list[McpToolInfo]:
        return list(self._tools)

    def call_tool(self, tool: str, arguments: dict[str, Any]) -> McpResult:
        self.calls.append((tool, dict(arguments)))
        if tool not in self._tool_results:
            raise KeyError(tool)
        return self._tool_results[tool]

    def list_resources(self) -> list[McpResourceInfo]:
        return list(self._resources)

    def read_resource(self, uri: str) -> McpResult:
        if uri not in self._resource_results:
            raise KeyError(uri)
        return self._resource_results[uri]
