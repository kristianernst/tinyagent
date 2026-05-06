"""Context construction and deterministic compaction."""

from tinyagent.core.context.builder import (
    ContextBuilder,
    estimate_messages_tokens,
    estimate_tokens,
    estimate_tools_tokens,
    message_text,
    render_context_checkpoint,
    render_environment_context,
    render_project_instructions,
    render_recent_tool_steps,
)
from tinyagent.core.context.checkpoint import (
    artifact_refs_from_tool_steps,
    compact_state,
    context_state_to_markdown,
    summarize_context_state,
)
from tinyagent.core.context.instructions import PROJECT_INSTRUCTION_FILE, load_project_instructions
from tinyagent.core.context.types import (
    ArtifactRef,
    BuiltContext,
    ContextConfig,
    ContextExclusion,
    ContextItem,
    ContextPlan,
    ContextState,
    ProjectInstructions,
)

__all__ = [
    "PROJECT_INSTRUCTION_FILE",
    "ArtifactRef",
    "BuiltContext",
    "ContextBuilder",
    "ContextConfig",
    "ContextExclusion",
    "ContextItem",
    "ContextPlan",
    "ContextState",
    "ProjectInstructions",
    "artifact_refs_from_tool_steps",
    "compact_state",
    "context_state_to_markdown",
    "estimate_messages_tokens",
    "estimate_tokens",
    "estimate_tools_tokens",
    "load_project_instructions",
    "message_text",
    "render_context_checkpoint",
    "render_environment_context",
    "render_project_instructions",
    "render_recent_tool_steps",
    "summarize_context_state",
]
