"""Context construction and compaction lifecycle helpers."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from tinyagent.core.context import BuiltContext, estimate_messages_tokens, estimate_tools_tokens, message_text
from tinyagent.core.contextfs import refresh_contextfs
from tinyagent.core.contracts import Profile, Tool
from tinyagent.core.state import RunState
from tinyagent.core.token_utils import estimate_tokens


def refresh_contextfs_if_enabled(
    state: RunState,
    *,
    contextfs_enabled: bool,
    data: Mapping[str, Any] | None = None,
) -> None:
    if not contextfs_enabled:
        return
    index_path = refresh_contextfs(state)
    state.emit("contextfs.index.updated", {"path": index_path, **(data or {})})


def build_context(
    state: RunState,
    profile: Profile,
    visible_tools: list[Tool],
    *,
    contextfs_enabled: bool,
) -> BuiltContext:
    refresh_contextfs_if_enabled(state, contextfs_enabled=contextfs_enabled)
    build_profile_context = getattr(profile, "build_context", None)
    if callable(build_profile_context):
        built_context = _call_profile_build_context(build_profile_context, state, visible_tools)
    else:
        messages = list(profile.build_messages(state))
        built_context = BuiltContext(
            messages=messages,
            token_estimate=estimate_messages_tokens(messages),
            static_context_tokens=sum(estimate_tokens(message_text(message)) for message in messages),
            tool_context_tokens=0,
            project_instruction_tokens=0,
        )
    token_estimate = built_context.token_estimate + estimate_tools_tokens(visible_tools)
    state.context_token_estimate = token_estimate
    return replace(built_context, token_estimate=token_estimate)


def _call_profile_build_context(
    build_profile_context: Callable[..., BuiltContext],
    state: RunState,
    visible_tools: list[Tool],
) -> BuiltContext:
    parameters = inspect.signature(build_profile_context).parameters
    if "visible_tools" in parameters:
        return build_profile_context(state, visible_tools=visible_tools)
    if "visible_tool_names" in parameters:
        return build_profile_context(state, visible_tool_names=[tool.name for tool in visible_tools])
    return build_profile_context(state)


def profile_should_compact(profile: Profile, state: RunState) -> bool:
    compact_check = getattr(profile, "should_compact", None)
    return callable(compact_check) and bool(compact_check(state))


def compact_context(
    state: RunState,
    profile: Profile,
    *,
    before_compact: Callable[[], None] | None = None,
) -> None:
    state.emit(
        "compaction.started",
        {
            "profile": profile.name,
            "token_estimate": state.context_token_estimate,
            "tool_step_count": len(state.tool_steps),
        },
    )
    if before_compact is not None:
        before_compact()
    profile.compact(state)
    state.transcript.record_compaction(
        item_id=f"transcript-compaction-{state.compaction_count:04d}",
        turn_id=state.current_turn_id,
        compaction_count=state.compaction_count,
        checkpoint_artifact=state.context_checkpoint_artifact or None,
    )
    state.emit(
        "checkpoint.completed",
        {
            "profile": profile.name,
            "compaction_count": state.compaction_count,
            "checkpoint_artifact": state.context_checkpoint_artifact or None,
        },
    )
