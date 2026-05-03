"""Zero-database runtime server for recorded and live runs."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from agentd.contracts import ApprovalHandler
from agentd.events import Event, EventSink, load_events_jsonl
from agentd.kernel import Kernel
from agentd.models import FakeModelProvider
from agentd.policy import default_policy
from agentd.profiles import ApexCoderProfile
from agentd.run_control import CancelToken
from agentd.run_graph import fork_run
from agentd.run_record import load_run_record
from agentd.state import ApprovalRequest, ApprovalResolution, ModelResponse, RunState, ToolCall
from agentd.tools import default_tools

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
TERMINAL_EVENT_TYPES = {"run.completed", "run.failed", "run.cancelled", "run.timed_out"}


@dataclass(frozen=True)
class RuntimeConfig:
    workspace: Path
    run_root: Path


class ApprovalBroker(ApprovalHandler):
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: dict[tuple[str, str], ApprovalRequest] = {}
        self._resolutions: dict[tuple[str, str], ApprovalResolution] = {}
        self._cancelled_runs: dict[str, str] = {}

    def resolve(self, request: ApprovalRequest, state: RunState) -> ApprovalResolution:
        key = (request.run_id, request.approval_id)
        with self._condition:
            self._pending[key] = request
            try:
                while key not in self._resolutions:
                    if state.cancel_token.cancelled or request.run_id in self._cancelled_runs:
                        return ApprovalResolution(
                            approval_id=request.approval_id,
                            decision="cancelled",
                            reason=self._cancelled_runs.get(request.run_id) or state.cancel_token.reason or "run_cancelled",
                        )
                    self._condition.wait(timeout=0.1)
                return self._resolutions.pop(key)
            finally:
                self._pending.pop(key, None)

    def approve(
        self,
        run_id: str,
        approval_id: str,
        *,
        decision: str = "approved",
        scope: str | None = "once",
        reason: str | None = "server_resolved",
    ) -> bool:
        if decision not in {"approved", "denied", "cancelled", "expired"}:
            raise ValueError(f"invalid approval decision: {decision}")
        if scope not in {None, "once", "run"}:
            raise ValueError(f"invalid approval scope: {scope}")
        key = (run_id, approval_id)
        with self._condition:
            if run_id in self._cancelled_runs:
                return False
            if key not in self._pending:
                return False
            self._resolutions[key] = ApprovalResolution(
                approval_id=approval_id,
                decision=decision,  # type: ignore[arg-type]
                scope=scope,  # type: ignore[arg-type]
                reason=reason,
            )
            self._condition.notify_all()
            return True

    def pending(self) -> list[dict[str, Any]]:
        with self._condition:
            return [request.to_json_dict() for request in self._pending.values()]

    def cancel_run(self, run_id: str, reason: str = "run_cancelled") -> None:
        with self._condition:
            self._cancelled_runs[run_id] = reason
            for key, request in list(self._pending.items()):
                if request.run_id == run_id:
                    self._resolutions[key] = ApprovalResolution(
                        approval_id=request.approval_id,
                        decision="cancelled",
                        reason=reason,
                    )
            self._condition.notify_all()

    def cleanup_run(self, run_id: str) -> None:
        with self._condition:
            self._cancelled_runs.pop(run_id, None)
            for key in [key for key in self._pending if key[0] == run_id]:
                self._pending.pop(key, None)
            for key in [key for key in self._resolutions if key[0] == run_id]:
                self._resolutions.pop(key, None)


class RunBus(EventSink):
    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._events_by_run: dict[str, list[Event]] = {}

    def emit(self, event: Event) -> None:
        with self._condition:
            self._events_by_run.setdefault(event.run_id, []).append(event)
            self._condition.notify_all()

    def events_after(self, run_id: str, after_seq: int = 0) -> list[Event]:
        with self._condition:
            return [event for event in self._events_by_run.get(run_id, []) if event.seq > after_seq]

    def wait_for_event(self, run_id: str, after_seq: int, timeout: float = 0.5) -> list[Event]:
        with self._condition:
            self._condition.wait_for(
                lambda: any(event.seq > after_seq for event in self._events_by_run.get(run_id, [])),
                timeout=timeout,
            )
            return [event for event in self._events_by_run.get(run_id, []) if event.seq > after_seq]

    def last_seq(self, run_id: str) -> int:
        with self._condition:
            events = self._events_by_run.get(run_id, [])
            return events[-1].seq if events else 0

    def cleanup_run(self, run_id: str) -> None:
        with self._condition:
            self._events_by_run.pop(run_id, None)


class RunStore:
    def __init__(self, run_root: Path) -> None:
        self.run_root = run_root.expanduser().resolve()
        self.run_root.mkdir(parents=True, exist_ok=True)

    def run_path(self, run_id: str) -> Path:
        _validate_run_id(run_id)
        path = (self.run_root / run_id).resolve()
        try:
            path.relative_to(self.run_root)
        except ValueError as exc:
            raise ValueError(f"run path escapes run root: {run_id}") from exc
        return path

    def exists(self, run_id: str) -> bool:
        return (self.run_path(run_id) / "events.jsonl").exists()

    def list_runs(self) -> list[dict[str, Any]]:
        runs = []
        for path in sorted(self.run_root.iterdir()):
            if path.is_dir() and (path / "events.jsonl").exists():
                try:
                    runs.append(self.run_summary(path.name))
                except ValueError:
                    continue
        return runs

    def run_summary(self, run_id: str, *, active: bool = False) -> dict[str, Any]:
        path = self.run_path(run_id)
        if not active and not (path / "events.jsonl").exists():
            raise FileNotFoundError(f"run not found: {run_id}")
        if (path / "metrics.json").exists():
            record = load_run_record(path)
            return record.to_json_dict()
        events = self.events(run_id)
        started = next((event for event in events if event.type == "run.started"), None)
        return {
            "run_path": str(path),
            "run_id": run_id,
            "task": started.data.get("task", "") if started else "",
            "status": _status_from_events(events, active=active),
            "event_count": events[-1].seq if events else 0,
            "event_log_only": True,
        }

    def events(self, run_id: str, *, after_seq: int = 0) -> list[Event]:
        path = self.run_path(run_id) / "events.jsonl"
        if not path.exists():
            return []
        return [event for event in load_events_jsonl(path) if event.seq > after_seq]

    def artifact_path(self, run_id: str, relative_path: str) -> Path:
        run_path = self.run_path(run_id).resolve()
        artifact = (run_path / relative_path).resolve()
        try:
            artifact.relative_to(run_path)
        except ValueError as exc:
            raise ValueError(f"artifact path escapes run: {relative_path}") from exc
        return artifact


class RunController:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self.store = RunStore(config.run_root)
        self.bus = RunBus()
        self.approvals = ApprovalBroker()
        self._lock = threading.Lock()
        self._cancel_tokens: dict[str, CancelToken] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._reserved_run_ids: set[str] = set()

    def start_run(self, task: str, *, run_id: str | None = None, approval_mode: str = "yolo") -> dict[str, Any]:
        token = CancelToken()
        resolved_run_id = run_id or f"run_server_{uuid4().hex}"
        output_dir = self.store.run_path(resolved_run_id)
        thread: threading.Thread
        with self._lock:
            if resolved_run_id in self._reserved_run_ids or output_dir.exists():
                raise ValueError(f"run already exists: {resolved_run_id}")
            self._reserved_run_ids.add(resolved_run_id)
            self._cancel_tokens[resolved_run_id] = token
        kernel = Kernel(
            model=FakeModelProvider(_fake_responses(task)),
            profile=ApexCoderProfile(),
            tools=default_tools(),
            policy=default_policy(),
            approval_handler=self.approvals,
            event_sink=self.bus,
            workspace_mode="current",
            approval_mode=approval_mode,  # type: ignore[arg-type]
        )
        def target() -> None:
            try:
                kernel.run(
                    task,
                    workspace=self.config.workspace,
                    run_id=resolved_run_id,
                    output_dir=output_dir,
                    cancel_token=token,
                    workspace_mode="current",
                    approval_mode=approval_mode,  # type: ignore[arg-type]
                )
            finally:
                with self._lock:
                    self._threads.pop(resolved_run_id, None)
                    self._cancel_tokens.pop(resolved_run_id, None)
                    self._reserved_run_ids.discard(resolved_run_id)
                self.approvals.cleanup_run(resolved_run_id)
                self.bus.cleanup_run(resolved_run_id)

        thread = threading.Thread(target=target, name=f"tinyagent-run-{resolved_run_id}", daemon=True)
        with self._lock:
            self._threads[resolved_run_id] = thread
        thread.start()
        return {"run_id": resolved_run_id, "run_path": str(output_dir), "status": "running"}

    def cancel(self, run_id: str, reason: str = "server_cancelled") -> bool:
        if any(event.type in TERMINAL_EVENT_TYPES for event in self.store.events(run_id)):
            self.cleanup()
            return False
        with self._lock:
            token = self._cancel_tokens.get(run_id)
        if token is None:
            return False
        token.cancel(reason)
        self.approvals.cancel_run(run_id, reason)
        return True

    def cleanup(self) -> None:
        with self._lock:
            completed = [run_id for run_id, thread in self._threads.items() if not thread.is_alive()]
            for run_id in completed:
                self._threads.pop(run_id, None)
                self._cancel_tokens.pop(run_id, None)

    def is_active(self, run_id: str) -> bool:
        self.cleanup()
        with self._lock:
            return run_id in self._threads

    def run_exists(self, run_id: str) -> bool:
        return self.is_active(run_id) or self.store.exists(run_id)

    def run_summary(self, run_id: str) -> dict[str, Any]:
        active = self.is_active(run_id)
        return self.store.run_summary(run_id, active=active)

    def events(self, run_id: str, after_seq: int = 0) -> list[Event]:
        if not self.run_exists(run_id):
            raise FileNotFoundError(f"run not found: {run_id}")
        events = {event.seq: event for event in self.store.events(run_id, after_seq=after_seq)}
        for event in self.bus.events_after(run_id, after_seq):
            events[event.seq] = event
        return [events[seq] for seq in sorted(events)]

    def should_stream(self, run_id: str, last_seq: int) -> bool:
        if self.is_active(run_id):
            return True
        return self.bus.last_seq(run_id) > last_seq

    def fork(self, run_id: str, at: str) -> dict[str, Any]:
        if not self.run_exists(run_id):
            raise FileNotFoundError(f"run not found: {run_id}")
        destination = fork_run(
            self.store.run_path(run_id),
            at,
        )
        return {"fork_dir": str(destination)}


class RuntimeHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], controller: RunController) -> None:
        self.controller = controller
        super().__init__(server_address, RuntimeHandler)


class RuntimeHandler(BaseHTTPRequestHandler):
    server: RuntimeHTTPServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        parts = _path_parts(parsed.path)
        try:
            if parts == ["api", "runs"]:
                self._json(HTTPStatus.OK, {"runs": self.server.controller.store.list_runs()})
                return
            if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                self._json(HTTPStatus.OK, self.server.controller.run_summary(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "events":
                self._events(parts[2], parsed.query)
                return
            if len(parts) >= 5 and parts[:2] == ["api", "runs"] and parts[3] == "artifacts":
                artifact = "/".join(parts[4:])
                self._artifact(parts[2], artifact)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except FileNotFoundError as exc:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (OSError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = _path_parts(parsed.path)
        body = self._read_body()
        try:
            if parts == ["api", "runs"]:
                task = str(body.get("task") or "")
                if not task:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "task is required"})
                    return
                self._json(
                    HTTPStatus.ACCEPTED,
                    self.server.controller.start_run(
                        task,
                        run_id=body.get("run_id"),
                        approval_mode=str(body.get("approval_mode") or "yolo"),
                    ),
                )
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "cancel":
                ok = self.server.controller.cancel(parts[2], str(body.get("reason") or "server_cancelled"))
                self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"cancelled": ok})
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "approve":
                approval_id = str(body.get("approval_id") or "")
                ok = self.server.controller.approvals.approve(
                    parts[2],
                    approval_id,
                    decision=str(body.get("decision") or "approved"),
                    scope=body.get("scope", "once"),
                    reason=body.get("reason") or "server_resolved",
                )
                self._json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"resolved": ok})
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "fork":
                if "output_dir" in body:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "custom fork output_dir is not supported by the HTTP API"})
                    return
                self._json(HTTPStatus.CREATED, self.server.controller.fork(parts[2], str(body.get("at") or "")))
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except FileNotFoundError as exc:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (OSError, ValueError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def _events(self, run_id: str, query: str) -> None:
        if not self.server.controller.run_exists(run_id):
            self._json(HTTPStatus.NOT_FOUND, {"error": f"run not found: {run_id}"})
            return
        after_seq = _after_seq(query, self.headers.get("Last-Event-ID"))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                events = self.server.controller.events(run_id, after_seq=after_seq)
                for event in events:
                    self._write_sse(event)
                    after_seq = max(after_seq, event.seq)
                if events and events[-1].type in TERMINAL_EVENT_TYPES:
                    break
                if not self.server.controller.should_stream(run_id, after_seq):
                    break
                if not events:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                self.server.controller.bus.wait_for_event(run_id, after_seq, timeout=0.5)
        except (BrokenPipeError, ConnectionError):
            return

    def _artifact(self, run_id: str, relative_path: str) -> None:
        if not self.server.controller.run_exists(run_id):
            self._json(HTTPStatus.NOT_FOUND, {"error": f"run not found: {run_id}"})
            return
        path = self.server.controller.store.artifact_path(run_id, unquote(relative_path))
        if not path.exists() or not path.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "artifact_not_found"})
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _write_sse(self, event: Event) -> None:
        payload = json.dumps(event.to_json_dict(), sort_keys=True)
        self.wfile.write(f"id: {event.seq}\nevent: {event.type}\ndata: {payload}\n\n".encode())
        self.wfile.flush()

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode() or "{}")

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def create_runtime_server(workspace: Path, host: str = "127.0.0.1", port: int = 8765, run_root: Path | None = None) -> RuntimeHTTPServer:
    resolved_workspace = workspace.expanduser().resolve()
    root = (run_root or resolved_workspace / ".tinyagent" / "runs").expanduser().resolve()
    controller = RunController(RuntimeConfig(workspace=resolved_workspace, run_root=root))
    return RuntimeHTTPServer((host, port), controller)


def _path_parts(path: str) -> list[str]:
    return [unquote(part) for part in path.split("/") if part]


def _after_seq(query: str, last_event_id: str | None) -> int:
    values = parse_qs(query).get("after_seq")
    candidate = values[0] if values else last_event_id
    try:
        return int(candidate or 0)
    except ValueError:
        return 0


def _status_from_events(events: list[Event], *, active: bool = False) -> str:
    if any(event.type == "run.cancelled" for event in events):
        return "cancelled"
    if any(event.type == "run.failed" for event in events):
        return "failed"
    if any(event.type == "run.completed" for event in events):
        return "completed"
    if active:
        return "running"
    return "incomplete" if events else "unknown"


def _validate_run_id(run_id: str) -> None:
    if not run_id or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(f"invalid run_id: {run_id}")


def _fake_responses(task: str) -> list[ModelResponse]:
    if "sleep" in task:
        return [
            ModelResponse(tool_calls=(ToolCall(id="call_sleep", name="shell", args={"cmd": "python -c 'import time; time.sleep(20)'"}),)),
            ModelResponse(content="sleep done", finish_reason="stop"),
        ]
    if "approval" in task:
        return [
            ModelResponse(tool_calls=(ToolCall(id="call_approval", name="shell", args={"cmd": "printf approved > ../approved.txt"}),)),
            ModelResponse(content="approval done", finish_reason="stop"),
        ]
    return [ModelResponse(content=f"Fake run finished: {task}", finish_reason="stop")]
