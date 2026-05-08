from __future__ import annotations

import threading
import time

from tinyagent.core.models import FakeModelProvider
from tinyagent.core.state import ModelResponse, ToolCall
from tinyagent.runtime.backend import ArtifactInfo, BackendRunHandle, HTTPRunBackend, LocalRunBackend, RunBackend, RunRequest
from tinyagent.runtime.coordination import CoordinationStore
from tinyagent.runtime.server import RuntimeConfig, RunController, RuntimeHTTPServer


def _controller(tmp_path, responses) -> RunController:
    return RunController(
        RuntimeConfig(
            workspace=tmp_path,
            run_root=tmp_path / ".tinyagent" / "runs",
            provider_factory=lambda _task: FakeModelProvider(responses),
            stream=False,
        )
    )


def test_local_run_backend_exposes_protocol_compatible_run_events_and_artifacts(tmp_path) -> None:
    from tinyagent.core.state import ModelResponse

    backend: RunBackend = LocalRunBackend(_controller(tmp_path, [ModelResponse(content="backend done", finish_reason="stop")]))

    handle = backend.start_run(RunRequest(task="backend task", run_id="run_backend"))
    for _ in range(100):
        events = list(backend.events("run_backend"))
        if events and events[-1].type == "run.completed":
            break
        time.sleep(0.02)

    run = backend.get_run("run_backend")
    artifacts = backend.artifacts("run_backend")

    assert isinstance(handle, BackendRunHandle)
    assert handle.run_id == "run_backend"
    assert run["run_id"] == "run_backend"
    assert run["links"]["events"] == "/v1/runs/run_backend/events"
    assert events[-1].type == "run.completed"
    assert any(isinstance(item, ArtifactInfo) and item.path == "final.md" and item.kind == "run_output" for item in artifacts)
    assert b"backend done" in backend.fetch_artifact("run_backend", "final.md")


def test_http_run_backend_matches_local_protocol_for_events_and_artifacts(tmp_path) -> None:
    controller = _controller(tmp_path, [ModelResponse(content="http backend done", finish_reason="stop")])
    server = RuntimeHTTPServer(("127.0.0.1", 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = HTTPRunBackend(f"http://127.0.0.1:{server.server_port}")
        handle = backend.start_run(RunRequest(task="backend task", run_id="run_http_backend"))
        for _ in range(100):
            events = list(backend.events("run_http_backend"))
            if events and events[-1].type == "run.completed":
                break
            time.sleep(0.02)

        artifacts = backend.artifacts("run_http_backend")

        assert handle.events_url == "/v1/runs/run_http_backend/events"
        assert backend.get_run("run_http_backend")["run_id"] == "run_http_backend"
        assert events[-1].type == "run.completed"
        assert any(item.path == "final.md" for item in artifacts)
        assert b"http backend done" in backend.fetch_artifact("run_http_backend", "final.md")
        try:
            backend.fetch_artifact("run_http_backend", "artifacts/model-response-0001.json")
        except PermissionError:
            pass
        else:
            raise AssertionError("expected hidden model artifact fetch to be forbidden")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_run_backend_resolves_pending_approval(tmp_path) -> None:
    controller = _controller(
        tmp_path,
        [
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="call_backend_approval",
                        name="shell",
                        args={"cmd": "printf backend-approved > ../backend-approved.txt"},
                    ),
                )
            ),
            ModelResponse(content="backend approval done", finish_reason="stop"),
        ],
    )
    server = RuntimeHTTPServer(("127.0.0.1", 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = HTTPRunBackend(f"http://127.0.0.1:{server.server_port}")
        backend.start_run(RunRequest(task="backend approval", run_id="run_http_backend_approval", approval_mode="on-request"))
        _wait_for_backend_event(backend, "run_http_backend_approval", "approval.requested")

        [approval] = backend.pending_approvals("run_http_backend_approval")
        assert backend.resolve_approval(
            "run_http_backend_approval",
            str(approval["approval_id"]),
            decision="approved",
            scope="once",
            reason="http_backend_test",
        )
        _wait_for_backend_event(backend, "run_http_backend_approval", "run.completed")

        assert (tmp_path.parent / "backend-approved.txt").read_text() == "backend-approved"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_http_run_backend_cancels_active_run(tmp_path) -> None:
    controller = _controller(
        tmp_path,
        [
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        id="call_backend_sleep",
                        name="shell",
                        args={"cmd": "python -c 'import time; time.sleep(20)'"},
                    ),
                )
            ),
            ModelResponse(content="sleep done", finish_reason="stop"),
        ],
    )
    server = RuntimeHTTPServer(("127.0.0.1", 0), controller)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        backend = HTTPRunBackend(f"http://127.0.0.1:{server.server_port}")
        backend.start_run(RunRequest(task="backend cancel", run_id="run_http_backend_cancel"))
        _wait_for_backend_event(backend, "run_http_backend_cancel", "tool.execution.started")

        assert backend.cancel("run_http_backend_cancel", reason="http_backend_cancel")
        _wait_for_backend_event(backend, "run_http_backend_cancel", "run.cancelled")

        assert backend.get_run("run_http_backend_cancel")["status"] == "cancelled"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_protocol_openapi_event_schema_matches_surface_payload_shape() -> None:
    from tinyagent.runtime.protocol_v1 import openapi_spec

    event_schema = openapi_spec()["components"]["schemas"]["Event"]["properties"]
    artifact_schema = openapi_spec()["components"]["schemas"]["Artifact"]["properties"]

    assert "time" in event_schema
    assert "created_at" not in event_schema
    assert "artifact_refs" in event_schema
    assert "safe_to_display" in artifact_schema


def test_coordination_store_writes_inspectable_task_claim_and_handoff_files(tmp_path) -> None:
    store = CoordinationStore(tmp_path)
    session = store.create("coord_test", state="# Shared State\n")

    task = store.create_task(session.session_id, "Update docs", task_id="task_docs")
    claim = store.claim_task(session.session_id, "task_docs", "run_a")
    handoff = store.handoff(session.session_id, from_run="run_a", to_run="run_b", summary="Docs updated; tests pending.")
    run_link = store.record_run(session.session_id, run_id="run_a", task_id="task_docs", summary="Completed docs update.")
    events = store.events(session.session_id)

    assert session.state_path.read_text() == "# Shared State\n"
    assert task["type"] == "task.created"
    assert claim["type"] == "task.claimed"
    assert handoff["type"] == "handoff"
    assert "Completed docs update." in run_link.read_text()
    assert [event["type"] for event in events] == ["task.created", "task.claimed", "handoff"]
    assert "artifacts/model-request" not in session.tasks_path.read_text()


def test_coordination_store_rejects_unsafe_ids(tmp_path) -> None:
    store = CoordinationStore(tmp_path)

    try:
        store.create("../escape")
    except ValueError as exc:
        assert "Invalid session id" in str(exc)
    else:
        raise AssertionError("expected unsafe session id to be rejected")


def _wait_for_backend_event(backend: HTTPRunBackend, run_id: str, event_type: str, timeout: float = 10) -> object:
    deadline = time.monotonic() + timeout
    latest = []
    while time.monotonic() < deadline:
        latest = list(backend.events(run_id))
        for event in latest:
            if event.type == event_type:
                return event
        time.sleep(0.05)
    raise AssertionError(f"event {event_type} not seen for {run_id}: {[event.type for event in latest]}")
