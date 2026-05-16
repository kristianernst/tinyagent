"""Optional LSP model tools."""

from __future__ import annotations

from tinyagent.core.contracts import ToolRuntime
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.tools.core import ToolError, error_result, resolve_workspace_path, visible_output
from tinyagent.extensions.lsp.manager import LspManager
from tinyagent.extensions.lsp.types import LspDiagnostic, LspLocation, LspSymbol


class LspSymbolsTool:
    name = "lsp_symbols"
    runtime = ToolRuntime(lock_key="lsp")
    schema = {
        "name": "lsp_symbols",
        "description": "List symbols from a file or workspace using an optional language server.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
    }

    def __init__(self, manager: LspManager) -> None:
        self.manager = manager

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        path = str(call.args.get("path") or "").strip() or None
        query = str(call.args.get("query") or "").strip() or None
        limit = min(max(int(call.args.get("limit", 50)), 1), 100)
        try:
            if path is not None:
                resolve_workspace_path(state, path)
            clients = [self.manager.client_for_path(path)] if path else self.manager.clients_for_workspace()
            clients = [client for client in clients if client is not None]
            if not clients:
                return _unavailable(self.name, call, "no LSP server is configured for this workspace or path")
            symbols = []
            for client in clients:
                symbols.extend(client.symbols(path=path, query=query, limit=max(limit - len(symbols), 0)))
                if len(symbols) >= limit:
                    break
            symbols = [symbol for symbol in symbols if _safe_path(state, symbol.path)]
        except Exception as exc:
            return error_result(self.name, call, exc)
        _emit_extension_event(state, "lsp.symbols.listed", {"path": path, "query": query, "result_count": len(symbols)})
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(_render_symbols(symbols), state),
            data={"path": path, "query": query, "result_count": len(symbols), "symbols": [_symbol_data(item) for item in symbols]},
            summary=f"LSP returned {len(symbols)} symbol(s).",
        )


class LspDefinitionTool:
    name = "lsp_definition"
    runtime = ToolRuntime(lock_key="lsp")
    schema = {
        "name": "lsp_definition",
        "description": "Find definition at path, line, and column using an optional language server.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "line": {"type": "integer", "minimum": 1},
                "column": {"type": "integer", "minimum": 1},
            },
            "required": ["path", "line", "column"],
        },
    }

    def __init__(self, manager: LspManager) -> None:
        self.manager = manager

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        return _location_query(self.name, call, state, self.manager, query="definition")


class LspReferencesTool:
    name = "lsp_references"
    runtime = ToolRuntime(lock_key="lsp")
    schema = {
        "name": "lsp_references",
        "description": "Find references at path, line, and column using an optional language server.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "line": {"type": "integer", "minimum": 1},
                "column": {"type": "integer", "minimum": 1},
                "include_declaration": {"type": "boolean"},
            },
            "required": ["path", "line", "column"],
        },
    }

    def __init__(self, manager: LspManager) -> None:
        self.manager = manager

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        return _location_query(self.name, call, state, self.manager, query="references")


class LspDiagnosticsTool:
    name = "lsp_diagnostics"
    runtime = ToolRuntime(lock_key="lsp")
    schema = {
        "name": "lsp_diagnostics",
        "description": "Return current diagnostics for a file or workspace using an optional language server.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
    }

    def __init__(self, manager: LspManager) -> None:
        self.manager = manager

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        path = str(call.args.get("path") or "").strip() or None
        try:
            if path is not None:
                resolve_workspace_path(state, path)
            clients = [self.manager.client_for_path(path)] if path else self.manager.clients_for_workspace()
            clients = [client for client in clients if client is not None]
            if not clients:
                return _unavailable(self.name, call, "no LSP server is configured for this workspace or path")
            diagnostics = []
            for client in clients:
                diagnostics.extend(client.diagnostics(path=path))
            diagnostics = [diagnostic for diagnostic in diagnostics if _safe_path(state, diagnostic.path)]
        except Exception as exc:
            return error_result(self.name, call, exc)
        _emit_extension_event(state, "lsp.diagnostics.listed", {"path": path, "result_count": len(diagnostics)})
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(_render_diagnostics(diagnostics), state),
            data={"path": path, "result_count": len(diagnostics), "diagnostics": [_diagnostic_data(item) for item in diagnostics]},
            summary=f"LSP returned {len(diagnostics)} diagnostic(s).",
        )


def _location_query(tool_name: str, call: ToolCall, state: RunState, manager: LspManager, *, query: str) -> ToolResult:
    path = str(call.args.get("path") or "").strip()
    line = max(int(call.args.get("line", 1)), 1)
    column = max(int(call.args.get("column", 1)), 1)
    try:
        resolve_workspace_path(state, path)
        client = manager.client_for_path(path)
        if client is None:
            return _unavailable(tool_name, call, "no LSP server is configured for this path")
        if query == "definition":
            locations = client.definition(path=path, line=line, column=column)
            event_type = "lsp.definition.resolved"
        else:
            locations = client.references(
                path=path,
                line=line,
                column=column,
                include_declaration=bool(call.args.get("include_declaration", False)),
            )
            event_type = "lsp.references.resolved"
    except Exception as exc:
        return error_result(tool_name, call, exc)
    locations = [location for location in locations if _safe_path(state, location.path)]
    _emit_extension_event(state, event_type, {"path": path, "line": line, "column": column, "result_count": len(locations)})
    return ToolResult(
        tool_name=tool_name,
        call_id=call.id,
        output=visible_output(_render_locations(query, locations), state),
        data={
            "path": path,
            "line": line,
            "column": column,
            "result_count": len(locations),
            "locations": [_location_data(item) for item in locations],
        },
        summary=f"LSP returned {len(locations)} {query} location(s).",
    )


def _unavailable(tool_name: str, call: ToolCall, reason: str) -> ToolResult:
    return ToolResult(
        tool_name=tool_name,
        call_id=call.id,
        output=f"LSP unavailable: {reason}",
        ok=False,
        failure_kind="unavailable",
        data={"reason": reason},
        summary=f"LSP unavailable: {reason}",
    )


def _render_symbols(symbols: list[LspSymbol]) -> str:
    lines = ["LSP symbols:"]
    if not symbols:
        lines.append("No symbols found.")
    for index, symbol in enumerate(symbols, start=1):
        lines.append(f"{index}. {symbol.name} ({symbol.kind}) {symbol.path}:{symbol.line}")
    return "\n".join(lines)


def _render_locations(label: str, locations: list[LspLocation]) -> str:
    lines = [f"LSP {label}:"]
    if not locations:
        lines.append("No locations found.")
    for index, location in enumerate(locations, start=1):
        lines.append(f"{index}. {location.path}:{location.line}:{location.column}")
    return "\n".join(lines)


def _render_diagnostics(diagnostics: list[LspDiagnostic]) -> str:
    lines = ["LSP diagnostics:"]
    if not diagnostics:
        lines.append("No diagnostics found.")
    for index, diagnostic in enumerate(diagnostics, start=1):
        lines.append(f"{index}. {diagnostic.path}:{diagnostic.line} [{diagnostic.severity}] {diagnostic.message}")
    return "\n".join(lines)


def _symbol_data(symbol: LspSymbol) -> dict[str, object]:
    return {
        "name": symbol.name,
        "kind": symbol.kind,
        "path": symbol.path,
        "line": symbol.line,
        "column": symbol.column,
        "end_line": symbol.end_line,
        "container": symbol.container,
    }


def _location_data(location: LspLocation) -> dict[str, object]:
    return {
        "path": location.path,
        "line": location.line,
        "column": location.column,
        "end_line": location.end_line,
        "end_column": location.end_column,
    }


def _diagnostic_data(diagnostic: LspDiagnostic) -> dict[str, object]:
    return {
        "path": diagnostic.path,
        "line": diagnostic.line,
        "message": diagnostic.message,
        "severity": diagnostic.severity,
        "code": diagnostic.code,
    }


def _safe_path(state: RunState, path: str) -> bool:
    try:
        resolve_workspace_path(state, path, allow_run_artifacts=False)
    except (OSError, ToolError, ValueError):
        return False
    return True


def _emit_extension_event(state: RunState, name: str, data: dict[str, object]) -> None:
    state.emit("extension.event", {"extension": "lsp", "name": name, **data})
