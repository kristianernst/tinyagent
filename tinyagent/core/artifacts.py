"""Small helpers for ToolResult artifact references."""

from __future__ import annotations

from collections.abc import Iterable

from tinyagent.core.state import ToolResult

TOOL_RESULT_ARTIFACT_KEYS = ("context_artifact", "output_artifact", "captured_output_artifact")


def artifact_refs_from_values(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def tool_result_artifact_refs(
    result: ToolResult,
    *,
    include_primary: bool = True,
    keys: tuple[str, ...] = TOOL_RESULT_ARTIFACT_KEYS,
) -> tuple[str, ...]:
    values: list[object] = [result.artifact_path] if include_primary else []
    values.extend(result.data.get(key) for key in keys)
    return artifact_refs_from_values(values)
