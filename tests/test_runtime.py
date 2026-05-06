from __future__ import annotations

import http.client
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import tinyagent.cli as cli
from tinyagent.app.product import ProductHome, WorkspaceStore
from tinyagent.app.server import create_product_runtime_server
from tinyagent.core.model_stream import ModelDelta
from tinyagent.core.state import Message, ModelResponse, RunState, ToolCall
from tinyagent.runtime.conversation import ConversationStore
from tinyagent.runtime.server import RunController, RuntimeConfig, RuntimeHTTPServer, create_runtime_server


def test_runtime_server_starts_run_streams_reconnects_and_reads_artifact(tmp_path) -> None:
    with _server(tmp_path) as base:
        created = _request(base, "POST", "/api/runs", {"task": "runtime smoke", "run_id": "run_runtime_smoke"})
        assert created["status"] == "running"
        _wait_for_status(base, "run_runtime_smoke", "completed")

        events = _sse(base, "/api/runs/run_runtime_smoke/events")
        event_types = [event["type"] for event in events]
        assert "run.started" in event_types
        assert "model.text.delta" in event_types
        assert "run.completed" in event_types

        event_snapshot = _request(base, "GET", "/api/runs/run_runtime_smoke/events.json")
        snapshot_types = [event["type"] for event in event_snapshot["events"]]
        assert "run.started" in snapshot_types
        assert "model.text.delta" in snapshot_types
        assert "run.completed" in snapshot_types

        after_first = _sse(base, "/api/runs/run_runtime_smoke/events?after_seq=1")
        assert after_first
        assert min(event["seq"] for event in after_first) > 1
        last_event_id = _sse(base, "/api/runs/run_runtime_smoke/events", headers={"Last-Event-ID": "1"})
        assert last_event_id
        assert min(event["seq"] for event in last_event_id) > 1

        summary = _request(base, "GET", "/api/runs/run_runtime_smoke")
        assert summary["run_id"] == "run_runtime_smoke"
        assert summary["status"] == "completed"

        final = _wait_for_artifact(base, "run_runtime_smoke", "final.md")
        assert b"Fake run finished: runtime smoke" in final


def test_runtime_default_sse_filters_internal_reasoning_but_keeps_surface_events(tmp_path) -> None:
    with _server(tmp_path, provider_factory=lambda _task: _InternalReasoningProvider()) as base:
        _request(base, "POST", "/api/runs", {"task": "stream private reasoning", "run_id": "run_private_stream"})
        _wait_for_status(base, "run_private_stream", "completed")

        events = _sse(base, "/api/runs/run_private_stream/events")

        assert "model.text.delta" in [event["type"] for event in events]
        assert not any(event["visibility"] == "internal" for event in events)
        assert not any(event["data"].get("delta") == "private thought" for event in events)
        model_started = next(event for event in events if event["type"] == "model.call.started")
        assert "context_artifact" not in model_started["data"]
        assert "context_report_artifact" not in model_started["data"]
        assert "logical_request_artifact" not in model_started["data"]
        assert "http_request_artifact" not in model_started["data"]


def test_runtime_post_runs_can_append_to_conversation_and_use_prior_context(tmp_path) -> None:
    with _server(tmp_path) as base:
        first = _request(
            base,
            "POST",
            "/api/conversations/conv_http_prior/turns",
            {"message": "first", "run_id": "run_http_conversation_1", "turn_id": "turn_1"},
        )
        assert first["conversation_id"] == "conv_http_prior"
        assert first["turn_id"] == "turn_1"
        _wait_for_status(base, "run_http_conversation_1", "completed")

        second = _request(
            base,
            "POST",
            "/api/conversations/conv_http_prior/turns",
            {"message": "second", "run_id": "run_http_conversation_2", "turn_id": "turn_2"},
        )
        assert second["conversation_id"] == "conv_http_prior"
        assert second["turn_id"] == "turn_2"
        _wait_for_status(base, "run_http_conversation_2", "completed")

        prior_context = tmp_path / ".tinyagent" / "runs" / "run_http_conversation_2" / "artifacts" / "prior-context.json"
        assert prior_context.exists()
        assert "first" in prior_context.read_text()
        assert "Fake run finished: first" in prior_context.read_text()

        conversations = _request(base, "GET", "/api/conversations")
        assert conversations["conversations"][0]["conversation_id"] == "conv_http_prior"
        assert conversations["conversations"][0]["title"] == "first"
        assert conversations["conversations"][0]["turn_count"] == 2


def test_runtime_conversation_start_turn_and_list_turns(tmp_path) -> None:
    with _server(tmp_path) as base:
        first = _request(
            base,
            "POST",
            "/api/conversations/conv_http/turns",
            {"message": "first", "run_id": "run_http_conversation_1", "turn_id": "turn_1"},
        )
        assert first["conversation_id"] == "conv_http"
        assert first["turn_id"] == "turn_1"
        assert first["events_url"] == "/api/runs/run_http_conversation_1/events"
        _wait_for_status(base, "run_http_conversation_1", "completed")

        conversations = _request(base, "GET", "/api/conversations")
        assert conversations["conversations"][0]["conversation_id"] == "conv_http"

        turns = _wait_for_conversation_turns(base, "conv_http", ["turn.started", "turn.completed"])
        assert turns["conversation_id"] == "conv_http"
        assert [turn["type"] for turn in turns["turns"]] == ["turn.started", "turn.completed"]
        assert turns["turns"][0]["conversation_id"] == "conv_http"


def test_runtime_product_conversation_root_is_visible_to_cli(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))
    assert cli.main(["init", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    [workspace_record_path] = list((home / "workspaces").glob("ws_*/workspace.json"))
    workspace_id = json.loads(workspace_record_path.read_text())["workspace_id"]
    conversation_root = home / "workspaces" / workspace_id / "conversations"

    with _server(workspace, conversation_root=conversation_root) as base:
        _request(
            base,
            "POST",
            "/api/conversations/conv_shared/turns",
            {"message": "shared", "run_id": "run_shared_conversation", "turn_id": "turn_1"},
        )
        _wait_for_status(base, "run_shared_conversation", "completed")
        _wait_for_conversation_turns(base, "conv_shared", ["turn.started", "turn.completed"])

    list_code = cli.main(["conversations", "--workspace", str(workspace), "list"])
    listed = capsys.readouterr()

    assert list_code == 0
    assert "conv_shared" in listed.out


def test_product_runtime_lists_workspaces_and_scopes_conversations(tmp_path) -> None:
    home = ProductHome(tmp_path / "home")
    workspace_a = tmp_path / "workspace-a"
    workspace_b = tmp_path / "workspace-b"
    workspace_a.mkdir()
    workspace_b.mkdir()
    store = WorkspaceStore(home)
    record_a = store.register(workspace_a, name="Workspace A")
    server = create_product_runtime_server(home, port=0, provider="fake", stream=True)
    base = f"127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        registered = _request(base, "POST", "/api/workspaces", {"path": str(workspace_b), "name": "Workspace B"})
        record_b = registered["workspace"]
        assert record_b["name"] == "Workspace B"

        workspaces = _request(base, "GET", "/api/workspaces")
        assert [workspace["workspace_id"] for workspace in workspaces["workspaces"]] == [
            record_b["workspace_id"],
            record_a.workspace_id,
        ]

        first = _request(
            base,
            "POST",
            "/api/conversations/conv_workspace_a/turns",
            {
                "workspace_id": record_a.workspace_id,
                "message": "first",
                "run_id": "run_workspace_a",
                "turn_id": "turn_1",
            },
        )
        assert first["conversation_id"] == "conv_workspace_a"
        _wait_for_status(base, "run_workspace_a", "completed", workspace_id=record_a.workspace_id)

        conversations_a = _request(base, "GET", f"/api/conversations?workspace_id={record_a.workspace_id}")
        conversations_b = _request(base, "GET", f"/api/conversations?workspace_id={record_b['workspace_id']}")
        assert conversations_a["conversations"][0]["conversation_id"] == "conv_workspace_a"
        assert conversations_b["conversations"] == []

        events = _request(base, "GET", f"/api/runs/run_workspace_a/events.json?workspace_id={record_a.workspace_id}")
        assert any(event["type"] == "run.completed" for event in events["events"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_runtime_retains_live_events_briefly_after_run_thread_exits(tmp_path) -> None:
    with _server(tmp_path) as base:
        _request(base, "POST", "/api/runs", {"task": "retention smoke", "run_id": "run_retention"})
        _wait_for_status(base, "run_retention", "completed")

        events = _sse(base, "/api/runs/run_retention/events")
        event_snapshot = _request(base, "GET", "/api/runs/run_retention/events.json")

        assert any(event["type"] == "model.text.delta" for event in events)
        assert any(event["type"] == "model.text.delta" for event in event_snapshot["events"])
        surface_log = tmp_path / ".tinyagent" / "runs" / "run_retention" / "surface-events.jsonl"
        surface_events = [json.loads(line) for line in surface_log.read_text().splitlines()]
        assert any(event["type"] == "model.text.delta" for event in surface_events)
        assert any(event["type"] == "run.completed" for event in surface_events)
        assert not any(event["visibility"] == "internal" for event in surface_events)


def test_runtime_surface_stream_correlates_tool_events_by_tool_call_id(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    with _server(tmp_path) as base:
        _request(base, "POST", "/api/runs", {"task": "read hello.txt", "run_id": "run_tool_surface"})
        _wait_for_status(base, "run_tool_surface", "completed")

        events = _sse(base, "/api/runs/run_tool_surface/events")

        assembled = next(event for event in events if event["type"] == "model.tool_call.assembly.completed")
        started = next(event for event in events if event["type"] == "tool.execution.started")
        completed = next(event for event in events if event["type"] == "tool.execution.completed")
        tool_call_id = assembled["data"]["tool_call_id"]
        assert tool_call_id
        assert started["data"]["tool_call_id"] == tool_call_id
        assert completed["data"]["tool_call_id"] == tool_call_id
        assert completed["visibility"] == "user"
        assert "artifact_path" not in completed["data"]
        assert "read_hints" not in completed["data"]
        assert "context_artifact" not in completed["data"]["data"]
        assert "output_artifact" in completed["data"]["data"]
        assert "context/" not in json.dumps(completed)


def test_runtime_default_sse_redacts_read_context_paths(tmp_path) -> None:
    with _server(tmp_path, provider_factory=lambda _task: _ReadContextProvider()) as base:
        _request(base, "POST", "/api/runs", {"task": "read context", "run_id": "run_read_context_surface"})
        _wait_for_status(base, "run_read_context_surface", "completed")

        events = _sse(base, "/api/runs/run_read_context_surface/events")

        completed = next(
            event
            for event in events
            if event["type"] == "tool.execution.completed" and event["data"].get("tool") == "read_context"
        )
        payload = json.dumps(completed)
        assert "context/" not in payload
        assert ".tinyagent/runs/" not in payload
        assert "[redacted]" in payload


def test_runtime_cancel_endpoint_stops_active_run(tmp_path) -> None:
    with _server(tmp_path) as base:
        _request(base, "POST", "/api/runs", {"task": "sleep please", "run_id": "run_runtime_cancel"})
        _wait_for_event(base, "run_runtime_cancel", "tool.execution.started")

        cancelled = _request(base, "POST", "/api/runs/run_runtime_cancel/cancel", {"reason": "test_cancel"})

        assert cancelled["cancelled"] is True
        summary = _wait_for_status(base, "run_runtime_cancel", "cancelled")
        assert summary["status"] == "cancelled"


def test_runtime_approval_endpoint_resolves_brokered_request(tmp_path) -> None:
    with _server(tmp_path) as base:
        _request(base, "POST", "/api/runs", {"task": "needs approval", "run_id": "run_runtime_approval", "approval_mode": "on-request"})
        _wait_for_event(base, "run_runtime_approval", "approval.requested")

        resolved = _request(
            base,
            "POST",
            "/api/runs/run_runtime_approval/approve",
            {"approval_id": "approval_call_approval", "decision": "approved", "scope": "once"},
        )

        assert resolved["resolved"] is True
        summary = _wait_for_status(base, "run_runtime_approval", "completed")
        assert summary["status"] == "completed"
        assert (tmp_path.parent / "approved.txt").read_text() == "approved"


def test_runtime_fork_endpoint_uses_recorded_event_boundary(tmp_path) -> None:
    with _server(tmp_path) as base:
        _request(base, "POST", "/api/runs", {"task": "fork runtime", "run_id": "run_runtime_fork"})
        _wait_for_status(base, "run_runtime_fork", "completed")
        forked = _request(base, "POST", "/api/runs/run_runtime_fork/fork", {"at": "1"})

        fork_dir = Path(forked["fork_dir"])
        assert (fork_dir / "fork.json").exists()


def test_runtime_rejects_path_escape_run_ids_and_unknown_runs(tmp_path) -> None:
    with _server(tmp_path) as base:
        _request_error(base, "POST", "/api/runs", {"task": "bad", "run_id": "../escape"}, expected=400)
        _request_error(base, "POST", "/api/runs", {"task": "bad", "run_id": "/tmp/escape"}, expected=400)
        _request_error(base, "GET", "/api/runs/missing", expected=404)
        _request_error(base, "GET", "/api/runs/missing/events", expected=404)
        _request_error(base, "GET", "/api/runs/missing/artifacts/final.md", expected=404)
        _request_error(base, "POST", "/api/runs/missing/cancel", {"reason": "nope"}, expected=404)
        _request_error(base, "POST", "/api/runs/missing/fork", {"at": "1"}, expected=404)
        _request_error(base, "GET", "/api/runs/%2Fetc/artifacts/passwd", expected=400)


def test_runtime_completed_runs_are_not_cancellable_and_fork_output_dir_is_rejected(tmp_path) -> None:
    with _server(tmp_path) as base:
        _request(base, "POST", "/api/runs", {"task": "done", "run_id": "run_terminal"})
        _wait_for_status(base, "run_terminal", "completed")

        cancel = _request_error(base, "POST", "/api/runs/run_terminal/cancel", {"reason": "too_late"}, expected=404)
        fork = _request_error(
            base,
            "POST",
            "/api/runs/run_terminal/fork",
            {"at": "1", "output_dir": str(tmp_path / "escape")},
            expected=400,
        )

        assert cancel["cancelled"] is False
        assert "output_dir" in fork["error"]


def test_runtime_rejects_concurrent_duplicate_run_ids(tmp_path) -> None:
    with _server(tmp_path) as base:
        def start() -> tuple[bool, dict]:
            try:
                return True, _request(base, "POST", "/api/runs", {"task": "sleep please", "run_id": "run_duplicate"})
            except AssertionError:
                return False, {}

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: start(), range(2)))

        assert [ok for ok, _payload in results].count(True) == 1
        _request(base, "POST", "/api/runs/run_duplicate/cancel", {"reason": "cleanup"})


def test_runtime_cancelled_approval_cannot_be_late_approved(tmp_path) -> None:
    with _server(tmp_path) as base:
        _request(base, "POST", "/api/runs", {"task": "needs approval", "run_id": "run_cancel_approval", "approval_mode": "on-request"})
        _wait_for_event(base, "run_cancel_approval", "approval.requested")

        assert _request(base, "POST", "/api/runs/run_cancel_approval/cancel", {"reason": "stop_waiting"})["cancelled"] is True
        late = _request_error(
            base,
            "POST",
            "/api/runs/run_cancel_approval/approve",
            {"approval_id": "approval_call_approval", "decision": "approved", "scope": "once"},
            expected=404,
        )
        summary = _wait_for_status(base, "run_cancel_approval", "cancelled")

        assert late["resolved"] is False
        assert summary["status"] == "cancelled"


class _server:
    def __init__(self, workspace: Path, *, provider_factory=None, conversation_root: Path | None = None) -> None:
        self.workspace = workspace
        self.provider_factory = provider_factory
        self.conversation_root = conversation_root
        self.server = None
        self.thread = None
        self.base = ""

    def __enter__(self) -> str:
        try:
            if self.provider_factory is None:
                self.server = create_runtime_server(
                    self.workspace,
                    port=0,
                    conversation_root=self.conversation_root or self.workspace / ".tinyagent" / "conversations",
                )
            else:
                self.server = RuntimeHTTPServer(
                    ("127.0.0.1", 0),
                    RunController(
                        RuntimeConfig(
                            workspace=self.workspace,
                            run_root=self.workspace / ".tinyagent" / "runs",
                            provider_factory=self.provider_factory,
                            stream=True,
                            debug_level=0,
                            conversation_store=ConversationStore(self.workspace / ".tinyagent" / "conversations"),
                        )
                    ),
                )
        except PermissionError as exc:
            pytest.skip(f"localhost socket binding unavailable: {exc}")
        self.base = f"127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self.base

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self.server is not None
        self.server.shutdown()
        self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)


def _request(base: str, method: str, path: str, body: dict | None = None) -> dict:
    raw = json.dumps(body or {}).encode()
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request(method, path, raw if body is not None else None, {"Content-Type": "application/json"} if body is not None else {})
        response = conn.getresponse()
        data = response.read()
        assert response.status < 400, data
        return json.loads(data or b"{}")
    finally:
        conn.close()


def _request_error(base: str, method: str, path: str, body: dict | None = None, *, expected: int) -> dict:
    raw = json.dumps(body or {}).encode()
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request(method, path, raw if body is not None else None, {"Content-Type": "application/json"} if body is not None else {})
        response = conn.getresponse()
        data = response.read()
        assert response.status == expected, data
        return json.loads(data or b"{}")
    finally:
        conn.close()


def _raw(base: str, method: str, path: str, headers: dict[str, str] | None = None) -> bytes:
    conn = http.client.HTTPConnection(base, timeout=10)
    try:
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        assert response.status < 400, data
        return data
    finally:
        conn.close()


def _sse(base: str, path: str, headers: dict[str, str] | None = None) -> list[dict]:
    raw = _raw(base, "GET", path, headers=headers).decode()
    events = []
    for chunk in raw.strip().split("\n\n"):
        data_line = next((line.removeprefix("data: ") for line in chunk.splitlines() if line.startswith("data: ")), "")
        if data_line:
            events.append(json.loads(data_line))
    return events


def _wait_for_status(base: str, run_id: str, status: str, timeout: float = 10, *, workspace_id: str | None = None) -> dict:
    deadline = time.monotonic() + timeout
    latest = {}
    suffix = f"?workspace_id={workspace_id}" if workspace_id else ""
    while time.monotonic() < deadline:
        latest = _request(base, "GET", f"/api/runs/{run_id}{suffix}")
        if latest.get("status") == status:
            return latest
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not reach status {status}: {latest}")


def _wait_for_event(base: str, run_id: str, event_type: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    conn = http.client.HTTPConnection(base, timeout=timeout)
    try:
        conn.request("GET", f"/api/runs/{run_id}/events")
        response = conn.getresponse()
        assert response.status < 400
        data_lines: list[str] = []
        while time.monotonic() < deadline:
            line = response.readline().decode()
            if not line:
                break
            if line.startswith("data: "):
                data_lines.append(line.removeprefix("data: ").strip())
            elif line == "\n" and data_lines:
                event = json.loads("".join(data_lines))
                if event["type"] == event_type:
                    return event
                data_lines = []
    finally:
        conn.close()
    raise AssertionError(f"event {event_type} not seen for {run_id}")


def _wait_for_artifact(base: str, run_id: str, path: str, timeout: float = 10) -> bytes:
    deadline = time.monotonic() + timeout
    last_error = b""
    while time.monotonic() < deadline:
        conn = http.client.HTTPConnection(base, timeout=10)
        try:
            conn.request("GET", f"/api/runs/{run_id}/artifacts/{path}")
            response = conn.getresponse()
            data = response.read()
            if response.status < 400:
                return data
            last_error = data
        finally:
            conn.close()
        time.sleep(0.05)
    raise AssertionError(f"artifact {path} not available: {last_error}")


def _wait_for_conversation_turns(base: str, conversation_id: str, expected_types: list[str], timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    latest = {}
    while time.monotonic() < deadline:
        latest = _request(base, "GET", f"/api/conversations/{conversation_id}/turns")
        if [turn["type"] for turn in latest.get("turns", [])] == expected_types:
            return latest
        time.sleep(0.05)
    raise AssertionError(f"conversation {conversation_id} did not reach turns {expected_types}: {latest}")


class _InternalReasoningProvider:
    name = "internal-reasoning"

    def complete(self, messages, tools, state: RunState) -> ModelResponse:
        del messages, tools, state
        return ModelResponse(content="public answer", finish_reason="stop")

    def stream(self, messages: list[Message], tools, state: RunState):
        del messages, tools, state
        yield ModelDelta(
            kind="reasoning_summary_delta",
            delta="private thought",
            data={"safe_to_display": False},
        )
        yield ModelDelta(kind="text_delta", delta="public answer")
        yield ModelDelta(kind="completed", data={"finish_reason": "stop"})


class _ReadContextProvider:
    name = "read-context"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, messages, tools, state: RunState) -> ModelResponse:
        del messages, tools, state
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=(ToolCall(id="call_read_context", name="read_context", args={"path": "context/INDEX.md"}),)
            )
        return ModelResponse(content="read context done", finish_reason="stop")
