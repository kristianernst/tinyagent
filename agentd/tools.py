"""Tool collection exports."""

from __future__ import annotations

from agentd.builtins.patch import ApplyPatchTool, apply_openai_patch, patch_paths
from agentd.builtins.shell import ShellTool, shell_preflight
from agentd.contracts import Tool
from agentd.tool_core import (
    SAFE_ENV_KEYS,
    ToolError,
    combined_output,
    error_result,
    is_relative_to,
    relative_workspace_path,
    resolve_workspace_path,
    safe_artifact_name,
    tool_env,
    visible_output,
    write_tool_output_artifact,
)
from agentd.tools_repo import (
    EXCLUDED_SEARCH_DIRS,
    MAX_READ_FILE_BYTES,
    ListFilesTool,
    ReadFileTool,
    SearchRepoTool,
    _run_rg_limited,
    repo_inspect_tools,
)


def builtin_tools() -> list[Tool]:
    return [ShellTool(), ApplyPatchTool()]


def all_tools() -> list[Tool]:
    return [*builtin_tools(), *repo_inspect_tools()]


def default_tools() -> list[Tool]:
    return all_tools()


__all__ = [
    "EXCLUDED_SEARCH_DIRS",
    "MAX_READ_FILE_BYTES",
    "SAFE_ENV_KEYS",
    "ApplyPatchTool",
    "ListFilesTool",
    "ReadFileTool",
    "SearchRepoTool",
    "ShellTool",
    "ToolError",
    "_combined_output",
    "_error_result",
    "_is_relative_to",
    "_run_rg_limited",
    "_safe_artifact_name",
    "_visible_output",
    "all_tools",
    "apply_openai_patch",
    "builtin_tools",
    "combined_output",
    "default_tools",
    "error_result",
    "is_relative_to",
    "patch_paths",
    "relative_workspace_path",
    "repo_inspect_tools",
    "resolve_workspace_path",
    "safe_artifact_name",
    "shell_preflight",
    "tool_env",
    "visible_output",
    "write_tool_output_artifact",
]

_combined_output = combined_output
_error_result = error_result
_is_relative_to = is_relative_to
_safe_artifact_name = safe_artifact_name
_visible_output = visible_output
