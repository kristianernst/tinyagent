"""LSP client protocol and fake client."""

from __future__ import annotations

from typing import Protocol

from tinyagent.extensions.lsp.types import LspDiagnostic, LspLocation, LspSymbol


class LspClient(Protocol):
    def symbols(self, *, path: str | None = None, query: str | None = None, limit: int = 100) -> list[LspSymbol]: ...

    def definition(self, *, path: str, line: int, column: int) -> list[LspLocation]: ...

    def references(self, *, path: str, line: int, column: int, include_declaration: bool = False) -> list[LspLocation]: ...

    def diagnostics(self, *, path: str | None = None) -> list[LspDiagnostic]: ...


class InMemoryLspClient:
    def __init__(
        self,
        *,
        symbols: list[LspSymbol] | None = None,
        definitions: dict[tuple[str, int, int], list[LspLocation]] | None = None,
        references: dict[tuple[str, int, int], list[LspLocation]] | None = None,
        diagnostics: list[LspDiagnostic] | None = None,
    ) -> None:
        self._symbols = tuple(symbols or ())
        self._definitions = dict(definitions or {})
        self._references = dict(references or {})
        self._diagnostics = tuple(diagnostics or ())

    def symbols(self, *, path: str | None = None, query: str | None = None, limit: int = 100) -> list[LspSymbol]:
        results = []
        needle = (query or "").lower()
        for symbol in self._symbols:
            if path and symbol.path != path:
                continue
            if needle and needle not in f"{symbol.name} {symbol.container}".lower():
                continue
            results.append(symbol)
            if len(results) >= limit:
                break
        return results

    def definition(self, *, path: str, line: int, column: int) -> list[LspLocation]:
        return list(self._definitions.get((path, line, column), ()))

    def references(self, *, path: str, line: int, column: int, include_declaration: bool = False) -> list[LspLocation]:
        del include_declaration
        return list(self._references.get((path, line, column), ()))

    def diagnostics(self, *, path: str | None = None) -> list[LspDiagnostic]:
        return [item for item in self._diagnostics if path is None or item.path == path]
