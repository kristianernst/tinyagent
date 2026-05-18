"""Model-visible deferred MCP tools."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping

from tinyagent.core.contextfs import write_context_tool_output
from tinyagent.core.contracts import ToolRuntime
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.token_utils import estimate_tokens, fits_token_budget
from tinyagent.core.tools.core import error_result, visible_output
from tinyagent.extensions.mcp.client import McpClient
from tinyagent.extensions.mcp.types import McpResourceInfo, McpResult, McpToolInfo


class McpSearchToolsTool:
    name = "mcp_search_tools"
    runtime = ToolRuntime(requires_network=True, lock_key="mcp")
    schema = {
        "name": "mcp_search_tools",
        "description": "Search available MCP tools without loading all schemas into context.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "server": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    }

    def __init__(self, clients: Mapping[str, McpClient]) -> None:
        self.clients = clients

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        query = str(call.args.get("query") or "").strip()
        if not query:
            return ToolResult(tool_name=self.name, call_id=call.id, output="query is required", ok=False)
        server = str(call.args.get("server") or "").strip() or None
        limit = min(max(int(call.args.get("limit", 10)), 1), 50)
        started = time.monotonic()
        try:
            tools = _search_tools(self.clients, query=query, server=server, limit=limit)
        except Exception as exc:
            return error_result(self.name, call, exc)
        _emit_extension_event(
            state,
            "mcp.tools.searched",
            {
                "query": query,
                "server": server,
                "result_count": len(tools),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "refs": [tool.qualified_name for tool in tools],
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(_render_tool_results(tools), state),
            data={"query": query, "server": server, "result_count": len(tools), "tools": [_tool_data(tool) for tool in tools]},
            summary=f"MCP tool search returned {len(tools)} result(s).",
        )


class McpLoadToolTool:
    name = "mcp_load_tool"
    runtime = ToolRuntime(requires_network=True, lock_key="mcp")
    schema = {
        "name": "mcp_load_tool",
        "description": "Load the full schema for one MCP tool without calling it.",
        "parameters": {
            "type": "object",
            "properties": {"server": {"type": "string"}, "tool": {"type": "string"}},
            "required": ["server", "tool"],
        },
    }

    def __init__(self, clients: Mapping[str, McpClient]) -> None:
        self.clients = clients

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        server = str(call.args.get("server") or "").strip()
        tool_name = str(call.args.get("tool") or "").strip()
        try:
            tool = _tool(self.clients, server, tool_name)
        except Exception as exc:
            return error_result(self.name, call, exc)
        output = "\n".join(
            [
                f"MCP tool: {tool.qualified_name}",
                f"description: {tool.description}",
                f"auth: {tool.auth}",
                f"permission: {tool.permission}",
                f"mutating: {tool.mutating}",
                "schema:",
                json.dumps(tool.input_schema, indent=2, sort_keys=True),
                "",
                f'call: mcp_call({{"server":"{server}","tool":"{tool.name}","arguments":{{}}}})',
            ]
        )
        _emit_extension_event(
            state,
            "mcp.tool.loaded",
            {"server": server, "tool": tool.name, "schema_tokens": estimate_tokens(json.dumps(tool.input_schema))},
        )
        artifact = None
        read_hints: list[str] = []
        output_tokens = estimate_tokens(output)
        if not fits_token_budget(output, state.budgets.max_tool_output_tokens_visible):
            artifact = write_context_tool_output(state, call, output, kind="mcp_tool_schema")
            read_hints = [f"context_read({{'ref':'contextfs:{artifact}'}})"]
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(output, state),
            data={
                "server": server,
                "tool": tool.name,
                "schema_tokens": estimate_tokens(json.dumps(tool.input_schema)),
                "output_tokens": output_tokens,
                "context_ref": f"contextfs:{artifact}" if artifact else "",
            },
            artifact_path=artifact,
            truncated=artifact is not None,
            summary=f"Loaded MCP tool schema for {tool.qualified_name}.",
            read_hints=read_hints,
        )


class McpCallTool:
    name = "mcp_call"
    runtime = ToolRuntime(requires_network=True, lock_key="mcp")
    schema = {
        "name": "mcp_call",
        "description": "Call one MCP tool after discovering and loading it.",
        "parameters": {
            "type": "object",
            "properties": {
                "server": {"type": "string"},
                "tool": {"type": "string"},
                "arguments": {"type": "object"},
            },
            "required": ["server", "tool", "arguments"],
        },
    }

    def __init__(self, clients: Mapping[str, McpClient]) -> None:
        self.clients = clients

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        server = str(call.args.get("server") or "").strip()
        tool_name = str(call.args.get("tool") or "").strip()
        arguments = call.args.get("arguments") or {}
        if not isinstance(arguments, dict):
            return ToolResult(tool_name=self.name, call_id=call.id, output="arguments must be an object", ok=False)
        try:
            client = _client(self.clients, server)
            _tool(self.clients, server, tool_name)
            result = client.call_tool(tool_name, arguments)
        except Exception as exc:
            return error_result(self.name, call, exc)
        return _result_tool_result(
            self.name,
            call,
            state,
            result,
            event_type="mcp.tool.called",
            event_data={"server": server, "tool": tool_name, "argument_keys": sorted(arguments)},
            summary=f"MCP {server}.{tool_name} returned {estimate_tokens(result.content)} tokens.",
        )


class McpReadResourceTool:
    name = "mcp_read_resource"
    runtime = ToolRuntime(requires_network=True, lock_key="mcp")
    schema = {
        "name": "mcp_read_resource",
        "description": "Read one MCP resource by URI.",
        "parameters": {
            "type": "object",
            "properties": {"server": {"type": "string"}, "uri": {"type": "string"}},
            "required": ["server", "uri"],
        },
    }

    def __init__(self, clients: Mapping[str, McpClient]) -> None:
        self.clients = clients

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        server = str(call.args.get("server") or "").strip()
        uri = str(call.args.get("uri") or "").strip()
        try:
            result = _client(self.clients, server).read_resource(uri)
        except Exception as exc:
            return error_result(self.name, call, exc)
        return _result_tool_result(
            self.name,
            call,
            state,
            result,
            event_type="mcp.resource.read",
            event_data={"server": server, "uri": uri},
            summary=f"MCP resource {server}:{uri} returned {estimate_tokens(result.content)} tokens.",
        )


def _client(clients: Mapping[str, McpClient], server: str) -> McpClient:
    if not server:
        raise ValueError("server is required")
    if server not in clients:
        raise KeyError(server)
    return clients[server]


def _tool(clients: Mapping[str, McpClient], server: str, tool_name: str) -> McpToolInfo:
    if not tool_name:
        raise ValueError("tool is required")
    for tool in _client(clients, server).list_tools():
        if tool.name == tool_name:
            if tool.exposure == "hidden":
                raise PermissionError(f"MCP tool is hidden: {server}.{tool_name}")
            return tool
    raise KeyError(f"{server}.{tool_name}")


def _search_tools(clients: Mapping[str, McpClient], *, query: str, server: str | None, limit: int) -> list[McpToolInfo]:
    needle = query.lower()
    results: list[McpToolInfo] = []
    for server_name, client in sorted(clients.items()):
        if server and server_name != server:
            continue
        for tool in client.list_tools():
            if tool.exposure == "hidden":
                continue
            haystack = f"{tool.server} {tool.name} {tool.description}".lower()
            if needle in haystack:
                results.append(tool)
                if len(results) >= limit:
                    return results
    return results


def _render_tool_results(tools: list[McpToolInfo]) -> str:
    lines = ["MCP tool results:"]
    if not tools:
        lines.append("No MCP tools found.")
    for index, tool in enumerate(tools, start=1):
        lines.extend(
            [
                "",
                f"{index}. {tool.qualified_name}",
                f"   server: {tool.server}",
                f"   description: {tool.description}",
                f"   auth: {tool.auth}",
                f"   permission: {tool.permission}",
                f'   load: mcp_load_tool({{"server":"{tool.server}","tool":"{tool.name}"}})',
            ]
        )
    return "\n".join(lines)


def _tool_data(tool: McpToolInfo) -> dict[str, object]:
    return {
        "server": tool.server,
        "tool": tool.name,
        "description": tool.description,
        "auth": tool.auth,
        "permission": tool.permission,
        "mutating": tool.mutating,
        "exposure": tool.exposure,
    }


def _result_tool_result(
    tool_name: str,
    call: ToolCall,
    state: RunState,
    result: McpResult,
    *,
    event_type: str,
    event_data: dict[str, object],
    summary: str,
) -> ToolResult:
    content = _result_content(result)
    artifact = None
    output_tokens = estimate_tokens(content)
    if not fits_token_budget(content, state.budgets.max_tool_output_tokens_visible):
        artifact = write_context_tool_output(state, call, content, kind="mcp_result")
        output = f"{summary}\nFull result: contextfs:{artifact}"
        truncated = True
    else:
        output = content
        truncated = False
    _emit_extension_event(
        state,
        event_type,
        {
            **event_data,
            "output_tokens": output_tokens,
            "context_ref": f"contextfs:{artifact}" if artifact else "",
        },
    )
    return ToolResult(
        tool_name=tool_name,
        call_id=call.id,
        output=visible_output(output, state),
        data={
            **event_data,
            "output_tokens": output_tokens,
            "context_ref": f"contextfs:{artifact}" if artifact else "",
        },
        artifact_path=artifact,
        truncated=truncated,
        summary=summary,
        read_hints=[f"context_read({{'ref':'contextfs:{artifact}'}})"] if artifact else [],
    )


def resource_data(resource: McpResourceInfo) -> dict[str, object]:
    return {
        "server": resource.server,
        "uri": resource.uri,
        "name": resource.name,
        "description": resource.description,
        "auth": resource.auth,
        "permission": resource.permission,
    }


def _result_content(result: McpResult) -> str:
    if result.structured_content is None:
        return result.content
    structured = json.dumps(result.structured_content, indent=2, sort_keys=True)
    if not result.content:
        return structured
    return f"{result.content}\n\n{structured}"


def _emit_extension_event(state: RunState, name: str, data: dict[str, object]) -> None:
    state.emit("extension.event", {"extension": "mcp", "name": name, **data})
