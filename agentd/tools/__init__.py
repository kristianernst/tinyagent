"""Tool collection exports."""

from __future__ import annotations

from agentd.contracts import Tool
from agentd.tools.builtins.edit import StrReplaceEditTool, WriteFileTool
from agentd.tools.builtins.patch import ApplyPatchTool, patch_paths
from agentd.tools.builtins.shell import ShellTool
from agentd.tools.core import resolve_workspace_path
from agentd.tools.repo import ListFilesTool, ReadFileTool, SearchRepoTool
from agentd.tools.repo import repo_inspect_tools as _repo_inspect_tools


def builtin_tools() -> list[Tool]:
    return [ShellTool(), ApplyPatchTool(), StrReplaceEditTool(), WriteFileTool()]


def all_tools() -> list[Tool]:
    return [*builtin_tools(), *_repo_inspect_tools()]


def default_tools() -> list[Tool]:
    return all_tools()


__all__ = [
    "ApplyPatchTool",
    "ListFilesTool",
    "ReadFileTool",
    "SearchRepoTool",
    "ShellTool",
    "StrReplaceEditTool",
    "WriteFileTool",
    "all_tools",
    "builtin_tools",
    "default_tools",
    "patch_paths",
    "resolve_workspace_path",
]
