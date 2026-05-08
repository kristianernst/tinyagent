"""LSP extension value types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LspLocation:
    path: str
    line: int
    column: int = 1
    end_line: int | None = None
    end_column: int | None = None


@dataclass(frozen=True)
class LspSymbol:
    name: str
    kind: str
    path: str
    line: int
    column: int = 1
    end_line: int | None = None
    container: str = ""


@dataclass(frozen=True)
class LspDiagnostic:
    path: str
    line: int
    message: str
    severity: str = "warning"
    code: str = ""
