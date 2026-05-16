from __future__ import annotations

import time

from tinyagent.core.models import FakeModelProvider
from tinyagent.core.state import ModelResponse, RunState, ToolCall, ToolResult, ToolStep, Workspace
from tinyagent.runtime.conversation import ConversationStore
from tinyagent.runtime.server import RunController, RuntimeConfig


def test_conversation_store_records_turn_and_reconstructs_prior_messages(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversations")
    conversation = store.create(workspace=tmp_path, title="Test conversation", conversation_id="conv_test")
    run_path = tmp_path / ".tinyagent" / "runs" / "run_one"
    run_path.mkdir(parents=True)
    (run_path / "final.md").write_text("# Final output\n\nassistant answer\n")

    started = store.record_turn_started(
        conversation_id=conversation.conversation_id,
        turn_id="turn_1",
        run_id="run_one",
        run_path=run_path,
        workspace=tmp_path,
        user_message=_message("user question"),
    )
    entry = store.record_turn(
        conversation_id=conversation.conversation_id,
        turn_id="turn_1",
        run_id="run_one",
        run_path=run_path,
        workspace=tmp_path,
        user_message=_message("user question"),
        assistant_message=_message("assistant answer", role="assistant"),
        tool_summary=[{"tool_call_id": "call_1", "tool": "shell", "ok": True, "summary": "ok", "artifact_refs": []}],
    )

    assert (tmp_path / "conversations" / "conv_test" / "conversation.json").exists()
    assert started["type"] == "turn.started"
    assert entry["run_id"] == "run_one"
    assert [turn["type"] for turn in store.turns(conversation.conversation_id)] == ["turn.started", "turn.completed"]
    prior = store.prior_messages(conversation.conversation_id)
    assert [(message.role, message.content) for message in prior] == [
        ("user", "user question"),
        ("assistant", "assistant answer"),
    ]
    listed = store.list(workspace=tmp_path)
    assert listed[0]["conversation_id"] == conversation.conversation_id
    assert listed[0]["title"] == "Test conversation"
    assert listed[0]["turn_count"] == 1
    assert listed[0]["last_run_id"] == "run_one"


def test_run_controller_conversation_turn_records_run_and_uses_prior_context(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversations")
    conversation = store.create(workspace=tmp_path, title="Conversation", conversation_id="conv_runtime")
    controller = RunController(
        RuntimeConfig(
            workspace=tmp_path,
            run_root=tmp_path / ".tinyagent" / "runs",
            provider_factory=lambda _task: FakeModelProvider([ModelResponse(content="answer", finish_reason="stop")]),
            stream=True,
            conversation_store=store,
        )
    )

    first = controller.start_conversation_turn(conversation.conversation_id, "first", turn_id="turn_1", run_id="run_conversation_1")
    assert store.turns(conversation.conversation_id)[-1]["type"] == "turn.started"
    assert store.turns(conversation.conversation_id)[-1]["run_id"] == "run_conversation_1"
    assert store.load(conversation.conversation_id).active_turn_id == "turn_1"
    _wait_until(lambda: not controller.is_active(first["run_id"]))
    second = controller.start_conversation_turn(conversation.conversation_id, "second", turn_id="turn_2", run_id="run_conversation_2")
    _wait_until(lambda: not controller.is_active(second["run_id"]))

    turns = store.turns(conversation.conversation_id)
    assert [(turn["type"], turn["run_id"]) for turn in turns] == [
        ("turn.started", "run_conversation_1"),
        ("turn.completed", "run_conversation_1"),
        ("turn.started", "run_conversation_2"),
        ("turn.completed", "run_conversation_2"),
    ]
    prior_context = tmp_path / ".tinyagent" / "runs" / "run_conversation_2" / "artifacts" / "prior-context.json"
    assert prior_context.exists()
    assert "first" in prior_context.read_text()
    assert "answer" in prior_context.read_text()


def test_conversation_run_turn_summarizes_all_tool_artifact_refs(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversations")
    conversation = store.create(workspace=tmp_path, title="Conversation", conversation_id="conv_artifacts")
    state = RunState.create("conversation artifacts", Workspace(tmp_path), run_id="run_artifacts")
    state.final_output = "done"
    state.tool_steps.append(
        ToolStep(
            call=ToolCall(name="shell", id="call_1"),
            result=ToolResult(
                tool_name="shell",
                call_id="call_1",
                output="ok",
                ok=True,
                artifact_path="context/shell/0001-call_1.txt",
                data={
                    "context_artifact": "context/shell/0001-call_1.txt",
                    "output_artifact": "artifacts/output.txt",
                    "captured_output_artifact": "artifacts/captured.txt",
                },
            ),
        )
    )

    entry = store.record_run_turn(conversation_id=conversation.conversation_id, turn_id="turn_1", user_content="hi", state=state)

    assert entry["tool_summary"][0]["artifact_refs"] == [
        "context/shell/0001-call_1.txt",
        "artifacts/output.txt",
        "artifacts/captured.txt",
    ]


def test_conversation_store_archives(tmp_path) -> None:
    store = ConversationStore(tmp_path / "conversations")
    conversation = store.create(workspace=tmp_path, title="Conversation", conversation_id="conv_test")

    assert conversation.conversation_id == "conv_test"
    assert store.conversation_path("conv_test") == tmp_path / "conversations" / "conv_test"

    archived = store.archive("conv_test")

    assert archived.status == "archived"
    assert store.load("conv_test").status == "archived"


def _message(content: str, *, role: str = "user"):
    from tinyagent.core.state import Message

    return Message(role=role, content=content)


def _wait_until(predicate, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition was not satisfied")
