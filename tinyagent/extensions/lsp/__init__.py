"""Optional LSP code-intelligence extension."""

from tinyagent.extensions.lsp.client import InMemoryLspClient, LspClient
from tinyagent.extensions.lsp.config import LspConfig, LspServerConfig, load_lsp_config
from tinyagent.extensions.lsp.extension import LspExtension
from tinyagent.extensions.lsp.manager import LspManager
from tinyagent.extensions.lsp.types import LspDiagnostic, LspLocation, LspSymbol

__all__ = [
    "InMemoryLspClient",
    "LspClient",
    "LspConfig",
    "LspDiagnostic",
    "LspExtension",
    "LspLocation",
    "LspManager",
    "LspServerConfig",
    "LspSymbol",
    "load_lsp_config",
]
