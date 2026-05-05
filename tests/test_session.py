from __future__ import annotations

import time

from agentd.models import FakeModelProvider
from agentd.runtime import RunController, RuntimeConfig
from agentd.session import SessionStore
from agentd.state import ModelResponse


def test_session_store_records_turn_and_reconstructs_prior_messages(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(workspace=tmp_path, title="Test session", session_id="sess_test")
    run_path = tmp_path / ".tinyagent" / "runs" / "run_one"
    run_path.mkdir(parents=True)
    (run_path / "final.md").write_text("# Final output\n\nassistant answer\n")

    started = store.record_turn_started(
        session_id=session.session_id,
        turn_id="turn_1",
        run_id="run_one",
        run_path=run_path,
        workspace=tmp_path,
        user_message=_message("user question"),
    )
    entry = store.record_turn(
        session_id=session.session_id,
        turn_id="turn_1",
        run_id="run_one",
        run_path=run_path,
        workspace=tmp_path,
        user_message=_message("user question"),
        assistant_message=_message("assistant answer", role="assistant"),
        tool_summary=[{"tool_call_id": "call_1", "tool": "shell", "ok": True, "summary": "ok", "artifact_refs": []}],
    )

    assert (tmp_path / "sessions" / "index.jsonl").exists()
    assert started["type"] == "turn.started"
    assert entry["run_id"] == "run_one"
    assert [turn["type"] for turn in store.turns(session.session_id)] == ["turn.started", "turn.completed"]
    prior = store.prior_messages(session.session_id)
    assert [(message.role, message.content) for message in prior] == [
        ("user", "user question"),
        ("assistant", "assistant answer"),
    ]
    listed = store.list(workspace=tmp_path)
    assert listed[0]["session_id"] == session.session_id
    assert listed[0]["title"] == "Test session"
    assert listed[0]["turn_count"] == 1
    assert listed[0]["last_run_id"] == "run_one"


def test_run_controller_session_turn_records_run_and_uses_prior_context(tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions")
    session = store.create(workspace=tmp_path, title="Session", session_id="sess_runtime")
    controller = RunController(
        RuntimeConfig(
            workspace=tmp_path,
            run_root=tmp_path / ".tinyagent" / "runs",
            provider_factory=lambda _task: FakeModelProvider([ModelResponse(content="answer", finish_reason="stop")]),
            stream=True,
            session_store=store,
        )
    )

    first = controller.start_session_turn(session.session_id, "first", turn_id="turn_1", run_id="run_session_1")
    assert store.turns(session.session_id)[-1]["type"] == "turn.started"
    assert store.turns(session.session_id)[-1]["run_id"] == "run_session_1"
    assert store.load(session.session_id).active_turn_id == "turn_1"
    _wait_until(lambda: not controller.is_active(first["run_id"]))
    second = controller.start_session_turn(session.session_id, "second", turn_id="turn_2", run_id="run_session_2")
    _wait_until(lambda: not controller.is_active(second["run_id"]))

    turns = store.turns(session.session_id)
    assert [(turn["type"], turn["run_id"]) for turn in turns] == [
        ("turn.started", "run_session_1"),
        ("turn.completed", "run_session_1"),
        ("turn.started", "run_session_2"),
        ("turn.completed", "run_session_2"),
    ]
    prior_context = tmp_path / ".tinyagent" / "runs" / "run_session_2" / "artifacts" / "prior-context.json"
    assert prior_context.exists()
    assert "first" in prior_context.read_text()
    assert "answer" in prior_context.read_text()


def _message(content: str, *, role: str = "user"):
    from agentd.state import Message

    return Message(role=role, content=content)


def _wait_until(predicate, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition was not satisfied")
