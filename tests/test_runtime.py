from __future__ import annotations

import http.client
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agentd.runtime import create_runtime_server


def test_runtime_server_starts_run_streams_reconnects_and_reads_artifact(tmp_path) -> None:
    with _server(tmp_path) as base:
        created = _request(base, "POST", "/api/runs", {"task": "runtime smoke", "run_id": "run_runtime_smoke"})
        assert created["status"] == "running"
        _wait_for_status(base, "run_runtime_smoke", "completed")

        events = _sse(base, "/api/runs/run_runtime_smoke/events")
        event_types = [event["type"] for event in events]
        assert "run.started" in event_types
        assert "run.completed" in event_types

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


def test_runtime_cancel_endpoint_stops_active_run(tmp_path) -> None:
    with _server(tmp_path) as base:
        _request(base, "POST", "/api/runs", {"task": "sleep please", "run_id": "run_runtime_cancel"})
        _wait_for_event(base, "run_runtime_cancel", "command.started")

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
        fork = _request_error(base, "POST", "/api/runs/run_terminal/fork", {"at": "1", "output_dir": str(tmp_path / "escape")}, expected=400)

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
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.server = None
        self.thread = None
        self.base = ""

    def __enter__(self) -> str:
        try:
            self.server = create_runtime_server(self.workspace, port=0)
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


def _wait_for_status(base: str, run_id: str, status: str, timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    latest = {}
    while time.monotonic() < deadline:
        latest = _request(base, "GET", f"/api/runs/{run_id}")
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
