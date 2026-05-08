"""Workspace index interfaces and fallback backends."""

from tinyagent.core.index.manager import WorkspaceIndexManager
from tinyagent.core.index.rg import RgWorkspaceIndex
from tinyagent.core.index.tools import SearchCodeTool
from tinyagent.core.index.types import IndexHit, IndexStatus, SyncResult, WorkspaceIndex

__all__ = [
    "IndexHit",
    "IndexStatus",
    "RgWorkspaceIndex",
    "SearchCodeTool",
    "SyncResult",
    "WorkspaceIndex",
    "WorkspaceIndexManager",
]
