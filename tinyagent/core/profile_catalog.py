"""Built-in profile names and runtime capability presets."""

from __future__ import annotations

from tinyagent.core.contracts import ProfileRuntimeCapabilities

DEFAULT_RUNTIME_CAPABILITIES = ProfileRuntimeCapabilities()
TINY_PI_RUNTIME_CAPABILITIES = ProfileRuntimeCapabilities(
    skills=False,
    dynamic_context=False,
    workspace_index=False,
    extensions=False,
    contextfs=False,
    tool_names=("read_file", "apply_patch", "str_replace_edit", "write_file", "shell"),
)

DEFAULT_PROFILE_NAMES = frozenset({"tiny-coder", "default", "apex", "apex-coder"})
TINY_PI_PROFILE_NAMES = frozenset({"tiny-pi", "pi", "minimal"})
