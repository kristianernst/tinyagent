"""Optional LSP extension wrapper."""

from __future__ import annotations

from collections.abc import Sequence

from tinyagent.core.context_sources.types import ContextSource
from tinyagent.core.contracts import Tool
from tinyagent.extensions.lsp.context import LspSymbolsSource
from tinyagent.extensions.lsp.manager import LspManager
from tinyagent.extensions.lsp.tools import LspDefinitionTool, LspDiagnosticsTool, LspReferencesTool, LspSymbolsTool


class LspExtension:
    name = "lsp"

    def __init__(self, manager: LspManager) -> None:
        self.manager = manager

    def tools(self) -> Sequence[Tool]:
        if not self.manager.config.enabled:
            return []
        return [
            LspSymbolsTool(self.manager),
            LspDefinitionTool(self.manager),
            LspReferencesTool(self.manager),
            LspDiagnosticsTool(self.manager),
        ]

    def context_sources(self) -> Sequence[ContextSource]:
        if not self.manager.config.enabled:
            return []
        return [LspSymbolsSource(self.manager)]
