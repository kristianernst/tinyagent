"""Tool collection exports."""

from __future__ import annotations

from tinyagent.core.contracts import Tool
from tinyagent.core.tools.context import ReadContextTool
from tinyagent.core.tools.builtins.edit import StrReplaceEditTool, WriteFileTool
from tinyagent.core.tools.builtins.patch import ApplyPatchTool, patch_paths
from tinyagent.core.tools.builtins.shell import ShellTool
from tinyagent.core.tools.core import resolve_workspace_path
from tinyagent.core.tools.repo import ListFilesTool, ReadFileTool, SearchRepoTool
from tinyagent.core.tools.repo import repo_inspect_tools as _repo_inspect_tools


def builtin_tools() -> list[Tool]:
    return [ShellTool(), ApplyPatchTool(), StrReplaceEditTool(), WriteFileTool()]


def all_tools() -> list[Tool]:
    return [*builtin_tools(), *_repo_inspect_tools(), ReadContextTool()]


def default_tools() -> list[Tool]:
    return all_tools()


__all__ = [
    "ApplyPatchTool",
    "ListFilesTool",
    "ReadFileTool",
    "ReadContextTool",
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
