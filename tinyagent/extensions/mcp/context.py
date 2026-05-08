"""MCP tool catalogue as a dynamic context source."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from tinyagent.core.context_sources.types import ContextChunk, ContextRef, ContextSourceInfo
from tinyagent.core.state import RunState
from tinyagent.extensions.mcp.client import McpClient
from tinyagent.extensions.mcp.tools import resource_data


class McpToolCatalogueSource:
    name = "mcp_tools"
    description = "Configured MCP tool and resource catalogue."
    priority = 0

    def __init__(self, clients: Mapping[str, McpClient]) -> None:
        self.clients = clients

    def info(self) -> ContextSourceInfo:
        return ContextSourceInfo(
            name=self.name,
            description="Configured MCP tool and resource catalogue.",
        )

    def search(
        self,
        query: str,
        *,
        workspace: Path,
        state: RunState,
        kind: str | None = None,
        limit: int = 10,
    ) -> Sequence[ContextRef]:
        del workspace, state
        needle = query.lower()
        refs: list[ContextRef] = []
        for server, client in sorted(self.clients.items()):
            for tool in client.list_tools():
                if kind not in {None, "tool", "mcp_tool"} or tool.exposure == "hidden":
                    continue
                haystack = f"{tool.server} {tool.name} {tool.description}".lower()
                if needle in haystack:
                    refs.append(
                        ContextRef(
                            ref=f"{self.name}:mcp-tool:{server}/{tool.name}",
                            source=self.name,
                            kind="mcp_tool",
                            title=tool.qualified_name,
                            summary=tool.description,
                        )
                    )
                    if len(refs) >= limit:
                        return refs
            for resource in client.list_resources():
                if kind not in {None, "resource", "mcp_resource"}:
                    continue
                haystack = f"{resource.server} {resource.uri} {resource.name} {resource.description}".lower()
                if needle in haystack:
                    refs.append(
                        ContextRef(
                            ref=f"{self.name}:mcp-resource:{server}/{resource.uri}",
                            source=self.name,
                            kind="mcp_resource",
                            title=resource.name or resource.uri,
                            summary=resource.description,
                        )
                    )
                    if len(refs) >= limit:
                        return refs
        return refs

    def read(
        self,
        ref: str,
        *,
        workspace: Path,
        state: RunState,
        start_line: int | None = None,
        max_lines: int | None = None,
    ) -> ContextChunk:
        del workspace, state, start_line, max_lines
        if ref.startswith("mcp-tool:"):
            server, tool_name = _split_ref(ref.removeprefix("mcp-tool:"))
            for tool in self.clients[server].list_tools():
                if tool.name == tool_name:
                    if tool.exposure == "hidden":
                        raise PermissionError(f"MCP tool is hidden: {server}.{tool_name}")
                    content = "\n".join(
                        [
                            f"tool: {tool.qualified_name}",
                            f"description: {tool.description}",
                            f"auth: {tool.auth}",
                            f"permission: {tool.permission}",
                            f"mutating: {tool.mutating}",
                            "schema:",
                            json.dumps(tool.input_schema, indent=2, sort_keys=True),
                        ]
                    )
                    return _chunk(ref, content, title=tool.qualified_name)
            raise KeyError(ref)
        if ref.startswith("mcp-resource:"):
            server, uri = _split_ref(ref.removeprefix("mcp-resource:"))
            for resource in self.clients[server].list_resources():
                if resource.uri == uri:
                    return _chunk(ref, json.dumps(resource_data(resource), indent=2, sort_keys=True), title=resource.name or uri)
            raise KeyError(ref)
        raise KeyError(ref)


def _split_ref(value: str) -> tuple[str, str]:
    server, sep, name = value.partition("/")
    if not sep or not server or not name:
        raise KeyError(value)
    return server, name


def _chunk(ref: str, content: str, *, title: str) -> ContextChunk:
    lines = content.splitlines()
    return ContextChunk(
        ref=ref,
        source="mcp_tools",
        title=title,
        content=content,
        start_line=1,
        end_line=len(lines),
        total_lines=len(lines),
        truncated=False,
    )
