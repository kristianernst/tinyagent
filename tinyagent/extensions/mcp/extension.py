"""Extension wrapper for deferred MCP exposure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from tinyagent.core.context_sources.types import ContextSource
from tinyagent.core.contracts import Tool
from tinyagent.extensions.mcp.client import McpClient
from tinyagent.extensions.mcp.context import McpToolCatalogueSource
from tinyagent.extensions.mcp.tools import McpCallTool, McpLoadToolTool, McpReadResourceTool, McpSearchToolsTool


class McpExtension:
    name = "mcp"

    def __init__(self, clients: Mapping[str, McpClient]) -> None:
        self.clients = dict(clients)

    def tools(self) -> Sequence[Tool]:
        return [
            McpSearchToolsTool(self.clients),
            McpLoadToolTool(self.clients),
            McpCallTool(self.clients),
            McpReadResourceTool(self.clients),
        ]

    def context_sources(self) -> Sequence[ContextSource]:
        return [McpToolCatalogueSource(self.clients)]
