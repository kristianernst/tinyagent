"""Deferred MCP extension."""

from tinyagent.extensions.mcp.client import InMemoryMcpClient, McpClient
from tinyagent.extensions.mcp.config import McpConfig, McpServerConfig, load_mcp_config
from tinyagent.extensions.mcp.extension import McpExtension
from tinyagent.extensions.mcp.types import McpResourceInfo, McpResult, McpToolInfo

__all__ = [
    "InMemoryMcpClient",
    "McpClient",
    "McpConfig",
    "McpExtension",
    "McpResourceInfo",
    "McpResult",
    "McpServerConfig",
    "McpToolInfo",
    "load_mcp_config",
]
