"""Generic post-processing for model-visible tool observations."""

from __future__ import annotations

from dataclasses import replace

from tinyagent.core.artifacts import tool_result_artifact_refs
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.token_utils import estimate_tokens, fits_token_budget
from tinyagent.core.tools.core import capture_tool_output, visible_output


def normalize_tool_result_output(state: RunState, call: ToolCall, result: ToolResult) -> ToolResult:
    """Keep large tool output recoverable without stuffing it into context."""

    output = result.output or ""
    output_tokens = _result_output_tokens(result, output)
    if fits_token_budget(output, state.budgets.max_tool_output_tokens_visible):
        return result

    if not tool_result_artifact_refs(result):
        captured = capture_tool_output(state, call, output, prefix="tool-output", kind="tool_output")
        data = {
            **result.data,
            **captured.data,
        }
        return replace(
            result,
            output=captured.preview,
            content_preview=captured.preview,
            artifact_path=captured.context_artifact,
            truncated=True,
            data=data,
            read_hints=[*result.read_hints, *captured.read_hints(failure=not result.ok)],
        )

    preview = result.content_preview or visible_output(output, state)
    if not fits_token_budget(preview, state.budgets.max_tool_output_tokens_visible):
        preview = visible_output(preview, state)
    data = {**result.data}
    data.setdefault("output_tokens", output_tokens)
    return replace(
        result,
        output=preview,
        content_preview=preview,
        truncated=True,
        data=data,
    )


def _result_output_tokens(result: ToolResult, output: str) -> int:
    output_tokens = result.data.get("output_tokens")
    if isinstance(output_tokens, int):
        return output_tokens
    return estimate_tokens(output)
