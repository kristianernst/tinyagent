from __future__ import annotations

from tinyagent.core.context import BuiltContext, estimate_messages_tokens, estimate_tools_tokens
from tinyagent.core.context_lifecycle import build_context, compact_context, profile_should_compact, refresh_contextfs_if_enabled
from tinyagent.core.state import Message, RunState, Workspace


class TinyProfile:
    name = "tiny-profile"

    def __init__(self, *, compact: bool = False) -> None:
        self.compact_enabled = compact

    def build_messages(self, state: RunState):
        return [Message(role="user", content=state.task)]

    def should_compact(self, state: RunState) -> bool:
        del state
        return self.compact_enabled

    def compact(self, state: RunState) -> None:
        state.compaction_count += 1
        state.context_checkpoint_artifact = "artifacts/context-checkpoint-0001.md"


class BuiltProfile(TinyProfile):
    def __init__(self, built_context: BuiltContext) -> None:
        super().__init__()
        self.built_context = built_context

    def build_context(self, state: RunState) -> BuiltContext:
        del state
        return self.built_context


class TinyTool:
    name = "tiny"
    schema = {"name": "tiny", "parameters": {"type": "object", "properties": {}}}


def test_build_context_uses_profile_messages_and_visible_tool_tokens(tmp_path) -> None:
    state = RunState.create("build context", Workspace(tmp_path))
    tool = TinyTool()
    messages = [Message(role="user", content="build context")]

    built = build_context(
        state,
        TinyProfile(),
        [tool],
        contextfs_enabled=False,
    )

    assert built.messages == messages
    assert built.token_estimate == estimate_messages_tokens(messages) + estimate_tools_tokens([tool])
    assert state.context_token_estimate == built.token_estimate
    assert "contextfs.index.updated" not in [event.type for event in state.events]


def test_build_context_preserves_profile_built_context_and_adds_visible_tool_tokens(tmp_path) -> None:
    state = RunState.create("profile context", Workspace(tmp_path))
    tool = TinyTool()
    profile_messages = [Message(role="system", content="abc")]
    profile_context = BuiltContext(
        messages=profile_messages,
        token_estimate=17,
        static_context_chars=3,
        tool_context_chars=5,
        project_instruction_chars=7,
        contextfs_index_path="context/INDEX.md",
    )

    built = build_context(
        state,
        BuiltProfile(profile_context),
        [tool],
        contextfs_enabled=False,
    )

    assert built.messages == profile_messages
    assert built.static_context_chars == 3
    assert built.tool_context_chars == 5
    assert built.project_instruction_chars == 7
    assert built.contextfs_index_path == "context/INDEX.md"
    assert built.token_estimate == 17 + estimate_tools_tokens([tool])
    assert state.context_token_estimate == built.token_estimate


def test_refresh_contextfs_respects_runtime_capability(tmp_path) -> None:
    state = RunState.create("refresh contextfs", Workspace(tmp_path), run_id="run_context_lifecycle")

    refresh_contextfs_if_enabled(state, contextfs_enabled=False, data={"phase": "disabled"})
    assert state.events == []

    refresh_contextfs_if_enabled(state, contextfs_enabled=True, data={"phase": "enabled"})
    event = state.events[-1]
    assert event.type == "contextfs.index.updated"
    assert event.data["phase"] == "enabled"
    assert event.data["path"] == "context/INDEX.md"


def test_compact_context_preserves_event_hook_transcript_order(tmp_path) -> None:
    state = RunState.create("compact context", Workspace(tmp_path))
    seen_before_compact: list[list[str]] = []

    compact_context(
        state,
        TinyProfile(compact=True),
        before_compact=lambda: seen_before_compact.append([event.type for event in state.events]),
    )

    assert profile_should_compact(TinyProfile(compact=True), state) is True
    assert [event.type for event in state.events] == ["compaction.started", "checkpoint.completed"]
    assert seen_before_compact == [["compaction.started"]]
    assert state.compaction_count == 1
    assert state.transcript.items[-1].kind == "compaction"
    assert state.transcript.items[-1].artifact_refs == ("artifacts/context-checkpoint-0001.md",)
