"""Builtin tinyagent tools."""

from tinyagent.core.tools.builtins.edit import StrReplaceEditTool, WriteFileTool
from tinyagent.core.tools.builtins.patch import ApplyPatchTool, apply_openai_patch, patch_paths
from tinyagent.core.tools.builtins.shell import ShellTool, shell_preflight

__all__ = [
    "ApplyPatchTool",
    "ShellTool",
    "StrReplaceEditTool",
    "WriteFileTool",
    "apply_openai_patch",
    "patch_paths",
    "shell_preflight",
]
