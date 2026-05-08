"""LSP symbols as a dynamic context source."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from tinyagent.core.context_sources.types import ContextChunk, ContextRef
from tinyagent.core.state import RunState
from tinyagent.core.tools.core import ToolError, resolve_workspace_path
from tinyagent.extensions.lsp.manager import LspManager


class LspSymbolsSource:
    name = "lsp_symbols"
    description = "Symbols from an optional language server."
    priority = 0

    def __init__(self, manager: LspManager) -> None:
        self.manager = manager

    def search(
        self,
        query: str,
        *,
        workspace: Path,
        state: RunState,
        kind: str | None = None,
        limit: int = 10,
    ) -> Sequence[ContextRef]:
        del workspace
        if kind not in {None, "symbol", "lsp_symbol"}:
            return []
        refs: list[ContextRef] = []
        for client in self.manager.clients_for_workspace():
            for symbol in client.symbols(query=query, limit=max(limit - len(refs), 0)):
                if not _safe_path(state, symbol.path):
                    continue
                refs.append(
                    ContextRef(
                        ref=f"{self.name}:symbol:{symbol.path}:{symbol.line}:{symbol.name}",
                        source=self.name,
                        kind="lsp_symbol",
                        title=symbol.name,
                        summary=f"{symbol.kind} in {symbol.path}:{symbol.line}",
                        path=symbol.path,
                        line_start=symbol.line,
                        line_end=symbol.end_line or symbol.line,
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
        parts = ref.split(":", 3)
        if len(parts) != 4 or parts[0] != "symbol":
            raise KeyError(ref)
        _prefix, path, line_text, name = parts
        content = f"{name}\npath: {path}\nline: {line_text}"
        return ContextChunk(
            ref=ref,
            source=self.name,
            title=name,
            content=content,
            start_line=1,
            end_line=3,
            total_lines=3,
            truncated=False,
        )


def _safe_path(state: RunState, path: str) -> bool:
    try:
        resolve_workspace_path(state, path, allow_run_artifacts=False)
    except (OSError, ToolError, ValueError):
        return False
    return True
