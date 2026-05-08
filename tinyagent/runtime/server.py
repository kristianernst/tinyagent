"""Zero-database runtime server for recorded and live runs."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from tinyagent.core.contracts import ApprovalHandler, ModelProvider
from tinyagent.core.events import Event, EventSink, event_debug_level, load_events_jsonl
from tinyagent.core.ids import validate_run_id
from tinyagent.core.index import WorkspaceIndexManager
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import ProviderError
from tinyagent.core.policy import default_policy
from tinyagent.core.profiles import profile_for
from tinyagent.core.resources import ResourceLoader, ResourceLoaderConfig
from tinyagent.core.providers.factory import ProviderSpec, provider_for
from tinyagent.core.run_control import CancelToken
from tinyagent.core.state import ApprovalMode, ApprovalRequest, ApprovalResolution, Message, RunState
from tinyagent.core.tools import default_tools
from tinyagent.core.workspace import SandboxModeInput, WorkspaceMode
from tinyagent.extensions.lsp import LspConfig
from tinyagent.extensions.mcp import McpClient, McpConfig, McpExtension
from tinyagent.extensions.todo_memory import TodoMemoryExtension
from tinyagent.runtime.conversation import ConversationStore
from tinyagent.runtime.protocol_v1 import V1_RUN_START_KEYS, error_response, health_response, openapi_spec, run_object
from tinyagent.runtime.run_graph import fork_run
from tinyagent.runtime.run_record import load_run_record

TERMINAL_EVENT_TYPES = {"run.completed", "run.failed", "run.cancelled", "run.timed_out"}
SURFACE_EVENT_TYPES = frozenset(
    {
        "run.started",
        "turn.started",
        "model.call.started",
        "model.text.delta",
        "model.message.completed",
        "model.tool_call.assembly.completed",
        "tool.execution.started",
        "tool.execution.completed",
        "tool.execution.failed",
        "tool.execution.blocked",
        "tool.execution.cancelled",
        "approval.requested",
        "approval.resolved",
        "artifact.created",
        "artifact.materialized",
        "workspace.mutation.detected",
        "run.completed",
        "run.failed",
        "run.cancelled",
    }
)
LIVE_BUFFER_TTL_SECONDS = 300.0
LIVE_BUFFER_MAX_EVENTS = 10_000
DEFAULT_SURFACE_REDACTED_EVENT_DATA_KEYS = frozenset(
    {
        "artifact_path",
        "context_artifact",
        "context_report_artifact",
        "logical_request_artifact",
        "http_request_artifact",
        "read_hints",
    }
)
DEFAULT_SURFACE_REDACTED_PATH_PATTERN = re.compile(
    r"(?:(?:[^\s\"']*/)?\.tinyagent/runs/[^\s\"']+/(?:context/[^\s\"']+|artifacts/(?:context|context-report|model-request)[^\s\"']*)"
    r"|context/[^\s\"']+"
    r"|artifacts/(?:context|context-report|model-request)[^\s\"']*)"
)


@dataclass(frozen=True)
class RuntimeConfig:
    workspace: Path
    run_root: Path
    provider_factory: Callable[[str], ModelProvider]
    stream: bool = True
    debug_level: int = 0
    workspace_mode: WorkspaceMode = "current"
    approval_mode: ApprovalMode = "yolo"
    sandbox_mode: SandboxModeInput = "none"
    profile: str = "tiny-coder"
    conversation_store: ConversationStore | None = None
    workspace_index_manager: WorkspaceIndexManager | None = None
    mcp_clients: Mapping[str, McpClient] | None = None
    mcp_config: McpConfig | None = None
    lsp_config: LspConfig | None = None
    todo_memory_enabled: bool = False
    memory_enabled: bool = False


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
    def __init__(self, *, ttl_seconds: float = LIVE_BUFFER_TTL_SECONDS, max_events: int = LIVE_BUFFER_MAX_EVENTS) -> None:
        self._condition = threading.Condition()
        self._events_by_run: dict[str, list[Event]] = {}
        self._terminal_at_by_run: dict[str, float] = {}
        self._ttl_seconds = ttl_seconds
        self._max_events = max_events

    def emit(self, event: Event) -> None:
        with self._condition:
            self._purge_expired_locked()
            self._events_by_run.setdefault(event.run_id, []).append(event)
            if len(self._events_by_run[event.run_id]) > self._max_events:
                self._events_by_run[event.run_id] = self._events_by_run[event.run_id][-self._max_events :]
            if event.type in TERMINAL_EVENT_TYPES:
                self._terminal_at_by_run[event.run_id] = time.monotonic()
            self._condition.notify_all()

    def events_after(self, run_id: str, after_seq: int = 0) -> list[Event]:
        with self._condition:
            self._purge_expired_locked()
            return [event for event in self._events_by_run.get(run_id, []) if event.seq > after_seq]

    def wait_for_event(self, run_id: str, after_seq: int, timeout: float = 0.5) -> list[Event]:
        with self._condition:
            self._purge_expired_locked()
            self._condition.wait_for(
                lambda: any(event.seq > after_seq for event in self._events_by_run.get(run_id, [])),
                timeout=timeout,
            )
            return [event for event in self._events_by_run.get(run_id, []) if event.seq > after_seq]

    def last_seq(self, run_id: str) -> int:
        with self._condition:
            self._purge_expired_locked()
            events = self._events_by_run.get(run_id, [])
            return events[-1].seq if events else 0

    def cleanup_run(self, run_id: str) -> None:
        self.mark_terminal(run_id)

    def mark_terminal(self, run_id: str) -> None:
        with self._condition:
            if run_id in self._events_by_run:
                self._terminal_at_by_run[run_id] = time.monotonic()
            else:
                self._terminal_at_by_run.pop(run_id, None)

    def _purge_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            run_id
            for run_id, terminal_at in self._terminal_at_by_run.items()
            if now - terminal_at >= self._ttl_seconds
        ]
        for run_id in expired:
            self._events_by_run.pop(run_id, None)
            self._terminal_at_by_run.pop(run_id, None)

    def drop_run(self, run_id: str) -> None:
        with self._condition:
            self._events_by_run.pop(run_id, None)
            self._terminal_at_by_run.pop(run_id, None)


class TeeEventSink(EventSink):
    def __init__(self, *sinks: EventSink) -> None:
        self._sinks = sinks

    def emit(self, event: Event) -> None:
        for sink in self._sinks:
            sink.emit(event)


class SurfaceEventLogSink(EventSink):
    def __init__(self, output_dir: Path, *, debug_level: int) -> None:
        self._path = output_dir / "surface-events.jsonl"
        self._debug_level = debug_level
        self._lock = threading.Lock()

    def emit(self, event: Event) -> None:
        if not _surface_event_visible(event, self._debug_level):
            return
        payload = _surface_event_dict(event, self._debug_level)
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a") as file:
                file.write(json.dumps(payload, sort_keys=True) + "\n")


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
        run_path = self.run_path(run_id)
        event_path = run_path / "events.jsonl"
        if not event_path.exists():
            return []
        events = {event.seq: event for event in load_events_jsonl(event_path) if event.seq > after_seq}
        surface_path = run_path / "surface-events.jsonl"
        if surface_path.exists():
            events.update(
                {
                    event.seq: event
                    for event in load_events_jsonl(surface_path)
                    if event.seq > after_seq
                }
            )
        return [events[seq] for seq in sorted(events)]

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

    def start_run(
        self,
        task: str,
        *,
        run_id: str | None = None,
        approval_mode: str | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        return self._start_run(task, run_id=run_id, approval_mode=approval_mode, profile=profile)

    def start_conversation_turn(
        self,
        conversation_id: str,
        task: str,
        *,
        turn_id: str | None = None,
        parent_turn_id: str | None = None,
        run_id: str | None = None,
        approval_mode: str | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        if self.config.conversation_store is None:
            raise ValueError("conversation store is not configured")
        resolved_turn_id = turn_id or f"turn_{uuid4().hex}"
        conversation = self.config.conversation_store.ensure(
            workspace=self.config.workspace,
            conversation_id=conversation_id,
            title=task[:80],
        )
        if conversation.status == "archived":
            raise ValueError(f"conversation is archived: {conversation_id}")
        self._wait_for_conversation_idle(conversation_id)
        prior_messages = self.config.conversation_store.prior_messages(conversation_id)
        return self._start_run(
            task,
            run_id=run_id,
            approval_mode=approval_mode,
            profile=profile,
            prior_messages=prior_messages,
            conversation_id=conversation_id,
            turn_id=resolved_turn_id,
            parent_turn_id=parent_turn_id,
        )

    def _wait_for_conversation_idle(self, conversation_id: str, *, timeout: float = 10.0) -> None:
        if self.config.conversation_store is None:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            turns = self.config.conversation_store.turns(conversation_id)
            completed = {
                str(turn.get("run_id"))
                for turn in turns
                if turn.get("type") == "turn.completed" and turn.get("run_id")
            }
            pending = [
                str(turn.get("run_id"))
                for turn in turns
                if turn.get("type") == "turn.started" and turn.get("run_id") and str(turn.get("run_id")) not in completed
            ]
            if not pending or not any(self.is_active(run_id) for run_id in pending):
                return
            time.sleep(0.05)

    def _start_run(
        self,
        task: str,
        *,
        run_id: str | None = None,
        approval_mode: str | None = None,
        profile: str | None = None,
        prior_messages=(),
        conversation_id: str | None = None,
        turn_id: str | None = None,
        parent_turn_id: str | None = None,
    ) -> dict[str, Any]:
        token = CancelToken()
        resolved_run_id = run_id or f"run_server_{uuid4().hex}"
        output_dir = self.store.run_path(resolved_run_id)
        thread: threading.Thread
        with self._lock:
            if resolved_run_id in self._reserved_run_ids or output_dir.exists():
                raise ValueError(f"run already exists: {resolved_run_id}")
            self._reserved_run_ids.add(resolved_run_id)
            self._cancel_tokens[resolved_run_id] = token
        resolved_approval_mode = approval_mode or self.config.approval_mode
        try:
            extensions = []
            if self.config.mcp_clients:
                extensions.append(McpExtension(self.config.mcp_clients))
            if self.config.todo_memory_enabled:
                extensions.append(TodoMemoryExtension())
            resolved_profile = profile_for(profile or self.config.profile)
            kernel = Kernel(
                model=self.config.provider_factory(task),
                profile=resolved_profile,
                tools=default_tools(),
                policy=default_policy(),
                approval_handler=self.approvals,
                event_sink=TeeEventSink(
                    self.bus,
                    SurfaceEventLogSink(output_dir, debug_level=self.config.debug_level),
                ),
                stream=self.config.stream,
                workspace_mode=self.config.workspace_mode,
                approval_mode=resolved_approval_mode,  # type: ignore[arg-type]
                sandbox_mode=self.config.sandbox_mode,
                workspace_index_manager=self.config.workspace_index_manager,
                extensions=extensions,
                resources=ResourceLoader(ResourceLoaderConfig(memory_enabled=self.config.memory_enabled)).load(
                    self.config.workspace,
                    profile=resolved_profile.name,
                ),
            )
        except Exception:
            with self._lock:
                self._cancel_tokens.pop(resolved_run_id, None)
                self._reserved_run_ids.discard(resolved_run_id)
            raise

        if conversation_id and turn_id and self.config.conversation_store is not None:
            self.config.conversation_store.record_turn_started(
                conversation_id=conversation_id,
                turn_id=turn_id,
                run_id=resolved_run_id,
                run_path=output_dir,
                workspace=self.config.workspace,
                user_message=Message(role="user", content=task),
                parent_turn_id=parent_turn_id,
            )

        def target() -> None:
            state: RunState | None = None
            try:
                state = kernel.run(
                    task,
                    workspace=self.config.workspace,
                    run_id=resolved_run_id,
                    output_dir=output_dir,
                    cancel_token=token,
                    stream=self.config.stream,
                    workspace_mode=self.config.workspace_mode,
                    approval_mode=resolved_approval_mode,  # type: ignore[arg-type]
                    sandbox_mode=self.config.sandbox_mode,
                    prior_messages=prior_messages,
                )
            finally:
                if state is not None and conversation_id and turn_id and self.config.conversation_store is not None:
                    self.config.conversation_store.record_run_turn(
                        conversation_id=conversation_id,
                        turn_id=turn_id,
                        user_content=task,
                        state=state,
                        parent_turn_id=parent_turn_id,
                    )
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
        payload = {"run_id": resolved_run_id, "run_path": str(output_dir), "status": "running"}
        if conversation_id:
            payload["conversation_id"] = conversation_id
        if turn_id:
            payload["turn_id"] = turn_id
        return payload

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

    def todo_state(self, run_id: str) -> dict[str, Any]:
        if not self.config.todo_memory_enabled:
            raise FileNotFoundError("todo memory extension is not enabled")
        if not self.run_exists(run_id):
            raise FileNotFoundError(f"run not found: {run_id}")
        path = self.store.run_path(run_id) / "context" / "memory" / "todo.json"
        if not path.exists():
            return {"version": 1, "items": [], "notes": ""}
        return json.loads(path.read_text())

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        if not self.run_exists(run_id):
            raise FileNotFoundError(f"run not found: {run_id}")
        run_path = self.store.run_path(run_id)
        items: dict[str, dict[str, Any]] = {}
        for event in self.events(run_id):
            if event.type != "artifact.created":
                continue
            path = event.data.get("path")
            if not isinstance(path, str) or _artifact_hidden_by_default(path):
                continue
            artifact_path = self.store.artifact_path(run_id, path)
            if not artifact_path.exists() or not artifact_path.is_file():
                continue
            stat = artifact_path.stat()
            items[path] = {
                "path": path,
                "kind": event.data.get("kind") or "artifact",
                "bytes": int(event.data.get("bytes") or stat.st_size),
                "created_at": event.time,
                "safe_to_display": True,
            }
        final = run_path / "final.md"
        if final.exists() and final.is_file():
            stat = final.stat()
            items.setdefault(
                "final.md",
                {
                    "path": "final.md",
                    "kind": "run_output",
                    "bytes": stat.st_size,
                    "created_at": "",
                    "safe_to_display": True,
                },
            )
        return [items[path] for path in sorted(items)]

    def public_artifact_path(self, run_id: str, relative_path: str) -> Path:
        path = self.store.artifact_path(run_id, relative_path)
        normalized = path.relative_to(self.store.run_path(run_id).resolve()).as_posix()
        if _artifact_hidden_by_default(normalized):
            raise PermissionError(f"artifact is not public: {normalized}")
        return path

    def mcp_servers(self) -> list[dict[str, Any]]:
        clients = self.config.mcp_clients or {}
        configured = {server.name: server for server in (self.config.mcp_config.servers if self.config.mcp_config else ())}
        if not clients and not configured:
            return []
        servers: list[dict[str, Any]] = []
        for name in sorted(set(clients) | set(configured)):
            client = clients.get(name)
            config = configured.get(name)
            if client is None:
                servers.append(
                    {
                        "name": name,
                        "enabled": bool(config.enabled) if config else False,
                        "status": "configured" if config and config.enabled else "disabled",
                        "tool_count": 0,
                        "resource_count": 0,
                        "error": "",
                    }
                )
                continue
            try:
                tools = client.list_tools()
                resources = client.list_resources()
                error = ""
            except Exception as exc:
                tools = []
                resources = []
                error = str(exc)
            servers.append(
                {
                    "name": name,
                    "enabled": True,
                    "status": "error" if error else "ready",
                    "tool_count": len(tools),
                    "resource_count": len(resources),
                    "error": error,
                }
            )
        return servers

    def lsp_servers(self) -> list[dict[str, Any]]:
        if self.config.lsp_config is None:
            return []
        return [
            {
                "name": server.name,
                "enabled": self.config.lsp_config.enabled and not server.disabled,
                "status": "configured" if self.config.lsp_config.enabled and not server.disabled else "disabled",
                "extensions": list(server.extensions),
                "permission": server.permission,
            }
            for server in self.config.lsp_config.servers
        ]


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
            if parts and parts[0] == "v1":
                self._v1_get(parts[1:], parsed)
                return
            if parts == ["api", "runs"]:
                self._json(HTTPStatus.OK, {"runs": self.server.controller.store.list_runs()})
                return
            if parts == ["api", "conversations"]:
                conversations = (
                    self.server.controller.config.conversation_store.list(workspace=self.server.controller.config.workspace)
                    if self.server.controller.config.conversation_store is not None
                    else []
                )
                self._json(HTTPStatus.OK, {"conversations": conversations})
                return
            if parts == ["api", "mcp", "servers"]:
                self._json(HTTPStatus.OK, {"servers": self.server.controller.mcp_servers()})
                return
            if parts == ["api", "lsp", "servers"]:
                self._json(HTTPStatus.OK, {"servers": self.server.controller.lsp_servers()})
                return
            if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "turns":
                if self.server.controller.config.conversation_store is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "conversation store is not configured"})
                    return
                self.server.controller.config.conversation_store.load(parts[2])
                turns = [
                    turn
                    for turn in self.server.controller.config.conversation_store.turns(parts[2])
                ]
                self._json(HTTPStatus.OK, {"conversation_id": parts[2], "turns": turns})
                return
            if len(parts) == 3 and parts[:2] == ["api", "runs"]:
                self._json(HTTPStatus.OK, self.server.controller.run_summary(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "events.json":
                self._events_json(parts[2], parsed.query)
                return
            if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "events":
                self._events(parts[2], parsed.query)
                return
            if len(parts) == 5 and parts[:2] == ["api", "runs"] and parts[3:] == ["memory", "todo"]:
                self._json(HTTPStatus.OK, self.server.controller.todo_state(parts[2]))
                return
            if len(parts) >= 5 and parts[:2] == ["api", "runs"] and parts[3] == "artifacts":
                artifact = "/".join(parts[4:])
                self._artifact(parts[2], artifact)
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except FileNotFoundError as exc:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (OSError, ValueError, ProviderError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        parts = _path_parts(parsed.path)
        try:
            body = self._read_body()
        except json.JSONDecodeError as exc:
            if parts and parts[0] == "v1":
                self._v1_error(HTTPStatus.BAD_REQUEST, "bad_request", f"Invalid JSON body: {exc}")
                return
            self._json(HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON body: {exc}"})
            return
        try:
            if parts and parts[0] == "v1":
                self._v1_post(parts[1:], parsed, body)
                return
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
                        approval_mode=str(body.get("approval_mode") or self.server.controller.config.approval_mode),
                        profile=str(body.get("profile") or self.server.controller.config.profile),
                    ),
                )
                return
            if len(parts) == 4 and parts[:2] == ["api", "conversations"] and parts[3] == "turns":
                task = str(body.get("message") or body.get("task") or "")
                if not task:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "message is required"})
                    return
                payload = self.server.controller.start_conversation_turn(
                    parts[2],
                    task,
                    run_id=body.get("run_id"),
                    turn_id=body.get("turn_id"),
                    parent_turn_id=body.get("parent_turn_id"),
                    approval_mode=str(body.get("approval_mode") or self.server.controller.config.approval_mode),
                    profile=str(body.get("profile") or self.server.controller.config.profile),
                )
                payload["events_url"] = f"/api/runs/{payload['run_id']}/events"
                self._json(HTTPStatus.ACCEPTED, payload)
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
            if parts == ["api", "mcp", "reload"]:
                self._json(HTTPStatus.OK, {"servers": self.server.controller.mcp_servers()})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except FileNotFoundError as exc:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except (OSError, ValueError, ProviderError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _v1_get(self, parts: list[str], parsed) -> None:
        try:
            if parts == ["health"]:
                self._json(HTTPStatus.OK, health_response())
                return
            if parts == ["openapi.json"]:
                self._json(HTTPStatus.OK, openapi_spec())
                return
            if parts == ["workspaces"]:
                self._json(
                    HTTPStatus.OK,
                    {
                        "items": [
                            {
                                "workspace_id": "default",
                                "id": "default",
                                "root": str(self.server.controller.config.workspace),
                                "name": self.server.controller.config.workspace.name,
                            }
                        ]
                    },
                )
                return
            if parts == ["runs"]:
                self._json(
                    HTTPStatus.OK,
                    {"items": [run_object(run) for run in self.server.controller.store.list_runs()]},
                )
                return
            if len(parts) >= 2 and parts[0] == "runs":
                self._v1_run_get_shared(
                    self.server.controller,
                    parts[1],
                    parts[2:],
                    parsed.query,
                    workspace_id=None,
                    conversation_id=_conversation_id_for_run(self.server.controller, parts[1]),
                )
                return
            self._v1_error(HTTPStatus.NOT_FOUND, "not_found", "Endpoint not found.")
        except FileNotFoundError as exc:
            self._v1_error(HTTPStatus.NOT_FOUND, _not_found_code(str(exc)), str(exc))
        except (OSError, ValueError, ProviderError) as exc:
            self._v1_error(HTTPStatus.BAD_REQUEST, _bad_request_code(str(exc)), str(exc))

    def _v1_post(self, parts: list[str], parsed, body: dict[str, Any]) -> None:
        del parsed
        try:
            if parts == ["runs"]:
                unsupported = sorted(set(body) - V1_RUN_START_KEYS)
                unsupported = [field for field in unsupported if field != "workspace_id"]
                if unsupported:
                    self._v1_error(HTTPStatus.BAD_REQUEST, "bad_request", f"Unsupported run fields: {', '.join(unsupported)}")
                    return
                task = str(body.get("task") or "").strip()
                if not task:
                    self._v1_error(HTTPStatus.BAD_REQUEST, "bad_request", "task is required")
                    return
                if body.get("conversation_id"):
                    payload = self.server.controller.start_conversation_turn(
                        str(body["conversation_id"]),
                        task,
                        run_id=body.get("run_id"),
                        turn_id=body.get("turn_id"),
                        parent_turn_id=body.get("parent_turn_id"),
                        approval_mode=str(body.get("approval_mode") or self.server.controller.config.approval_mode),
                        profile=str(body.get("profile") or self.server.controller.config.profile),
                    )
                else:
                    payload = self.server.controller.start_run(
                        task,
                        run_id=body.get("run_id"),
                        approval_mode=str(body.get("approval_mode") or self.server.controller.config.approval_mode),
                        profile=str(body.get("profile") or self.server.controller.config.profile),
                    )
                self._json(
                    HTTPStatus.ACCEPTED,
                    {"run": run_object(payload), "events_url": f"/v1/runs/{payload['run_id']}/events"},
                )
                return
            if len(parts) == 3 and parts[0] == "runs" and parts[2] == "cancel":
                ok = self.server.controller.cancel(parts[1], str(body.get("reason") or "server_cancelled"))
                if not ok:
                    self._v1_error(HTTPStatus.NOT_FOUND, "run_not_active", f"Run is not active: {parts[1]}")
                    return
                self._json(HTTPStatus.OK, {"cancelled": True})
                return
            if len(parts) == 5 and parts[0] == "runs" and parts[2] == "approvals" and parts[4] == "resolve":
                ok = self.server.controller.approvals.approve(
                    parts[1],
                    parts[3],
                    decision=str(body.get("decision") or "approved"),
                    scope=body.get("scope", "once"),
                    reason=body.get("reason") or "server_resolved",
                )
                if not ok:
                    self._v1_error(HTTPStatus.NOT_FOUND, "approval_not_found", f"Approval not found: {parts[3]}")
                    return
                self._json(HTTPStatus.OK, {"resolved": True})
                return
            self._v1_error(HTTPStatus.NOT_FOUND, "not_found", "Endpoint not found.")
        except FileNotFoundError as exc:
            self._v1_error(HTTPStatus.NOT_FOUND, _not_found_code(str(exc)), str(exc))
        except (OSError, ValueError, ProviderError) as exc:
            self._v1_error(HTTPStatus.BAD_REQUEST, _bad_request_code(str(exc)), str(exc))

    def _v1_run_get_shared(
        self,
        controller: RunController,
        run_id: str,
        tail: list[str],
        query: str,
        *,
        workspace_id: str | None,
        conversation_id: str = "",
    ) -> None:
        if not tail:
            self._json(HTTPStatus.OK, {"run": run_object(controller.run_summary(run_id), workspace_id=workspace_id)})
            return
        if tail == ["events"]:
            self._v1_events_shared(controller, run_id, query, workspace_id=workspace_id, conversation_id=conversation_id)
            return
        if tail in (["events.json"], ["events.jsonl"]):
            self._v1_events_json_shared(controller, run_id, query, workspace_id=workspace_id, conversation_id=conversation_id)
            return
        if tail == ["artifacts"]:
            if not controller.run_exists(run_id):
                self._v1_error(HTTPStatus.NOT_FOUND, "run_not_found", f"Run not found: {run_id}")
                return
            self._json(HTTPStatus.OK, {"items": controller.artifacts(run_id)})
            return
        if len(tail) >= 2 and tail[0] == "artifacts":
            self._v1_artifact_shared(controller, run_id, "/".join(tail[1:]))
            return
        if tail == ["approvals"]:
            if not controller.run_exists(run_id):
                self._v1_error(HTTPStatus.NOT_FOUND, "run_not_found", f"Run not found: {run_id}")
                return
            approvals = [approval for approval in controller.approvals.pending() if approval.get("run_id") == run_id]
            self._json(HTTPStatus.OK, {"items": approvals})
            return
        self._v1_error(HTTPStatus.NOT_FOUND, "not_found", "Endpoint not found.")

    def _v1_events_json_shared(
        self,
        controller: RunController,
        run_id: str,
        query: str,
        *,
        workspace_id: str | None,
        conversation_id: str = "",
    ) -> None:
        if not controller.run_exists(run_id):
            self._v1_error(HTTPStatus.NOT_FOUND, "run_not_found", f"Run not found: {run_id}")
            return
        after_seq = _after_seq(query, self.headers.get("Last-Event-ID"))
        events = [
            {**event, "workspace_id": workspace_id or "", "conversation_id": conversation_id}
            for event in (
                _surface_event_dict(item, controller.config.debug_level)
                for item in controller.events(run_id, after_seq=after_seq)
                if self._event_visible_for_controller(controller, item)
            )
        ]
        self._json(HTTPStatus.OK, {"items": events})

    def _v1_events_shared(
        self,
        controller: RunController,
        run_id: str,
        query: str,
        *,
        workspace_id: str | None,
        conversation_id: str = "",
    ) -> None:
        if not controller.run_exists(run_id):
            self._v1_error(HTTPStatus.NOT_FOUND, "run_not_found", f"Run not found: {run_id}")
            return
        after_seq = _after_seq(query, self.headers.get("Last-Event-ID"))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                events = controller.events(run_id, after_seq=after_seq)
                for event in events:
                    if self._event_visible_for_controller(controller, event):
                        payload = _surface_event_dict(event, controller.config.debug_level)
                        payload["workspace_id"] = workspace_id or ""
                        payload["conversation_id"] = conversation_id
                        self.wfile.write(
                            f"id: {event.seq}\nevent: {event.type}\ndata: {json.dumps(payload, sort_keys=True)}\n\n".encode()
                        )
                        self.wfile.flush()
                    after_seq = max(after_seq, event.seq)
                if events and events[-1].type in TERMINAL_EVENT_TYPES:
                    break
                if not controller.should_stream(run_id, after_seq):
                    break
                if not events:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                controller.bus.wait_for_event(run_id, after_seq, timeout=0.5)
        except (BrokenPipeError, ConnectionError):
            return

    def _v1_artifact_shared(self, controller: RunController, run_id: str, relative_path: str) -> None:
        if not controller.run_exists(run_id):
            self._v1_error(HTTPStatus.NOT_FOUND, "run_not_found", f"Run not found: {run_id}")
            return
        try:
            path = controller.public_artifact_path(run_id, unquote(relative_path))
        except PermissionError as exc:
            self._v1_error(HTTPStatus.FORBIDDEN, "forbidden", str(exc))
            return
        if not path.exists() or not path.is_file():
            self._v1_error(HTTPStatus.NOT_FOUND, "artifact_not_found", f"Artifact not found: {relative_path}")
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _event_visible_for_controller(self, controller: RunController, event: Event) -> bool:
        return _surface_event_visible(event, controller.config.debug_level)

    def _v1_error(self, status: HTTPStatus, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        self._json(status, error_response(code, message, details))

    def log_message(self, format: str, *args: Any) -> None:
        del format, args

    def _events(self, run_id: str, query: str) -> None:
        controller = self._controller_for_run(run_id, query)
        if not controller.run_exists(run_id):
            self._json(HTTPStatus.NOT_FOUND, {"error": f"run not found: {run_id}"})
            return
        after_seq = _after_seq(query, self.headers.get("Last-Event-ID"))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                events = controller.events(run_id, after_seq=after_seq)
                for event in events:
                    if self._event_visible(event):
                        self._write_sse(event)
                    after_seq = max(after_seq, event.seq)
                if events and events[-1].type in TERMINAL_EVENT_TYPES:
                    break
                if not controller.should_stream(run_id, after_seq):
                    break
                if not events:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                controller.bus.wait_for_event(run_id, after_seq, timeout=0.5)
        except (BrokenPipeError, ConnectionError):
            return

    def _events_json(self, run_id: str, query: str) -> None:
        controller = self._controller_for_run(run_id, query)
        if not controller.run_exists(run_id):
            self._json(HTTPStatus.NOT_FOUND, {"error": f"run not found: {run_id}"})
            return
        after_seq = _after_seq(query, self.headers.get("Last-Event-ID"))
        events = [
            _surface_event_dict(event, controller.config.debug_level)
            for event in controller.events(run_id, after_seq=after_seq)
            if self._event_visible(event)
        ]
        self._json(HTTPStatus.OK, {"events": events})

    def _artifact(self, run_id: str, relative_path: str, *, workspace_id: str | None = None) -> None:
        controller = self._controller_for_run(run_id, f"workspace_id={workspace_id}" if workspace_id else "")
        if not controller.run_exists(run_id):
            self._json(HTTPStatus.NOT_FOUND, {"error": f"run not found: {run_id}"})
            return
        try:
            path = controller.public_artifact_path(run_id, unquote(relative_path))
        except PermissionError as exc:
            self._json(HTTPStatus.FORBIDDEN, {"error": str(exc)})
            return
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
        payload = json.dumps(_surface_event_dict(event, self._controller_for_run(event.run_id, "").config.debug_level), sort_keys=True)
        self.wfile.write(f"id: {event.seq}\nevent: {event.type}\ndata: {payload}\n\n".encode())
        self.wfile.flush()

    def _event_visible(self, event: Event) -> bool:
        return _surface_event_visible(event, self._controller_for_run(event.run_id, "").config.debug_level)

    def _controller_for_run(self, run_id: str, query: str) -> RunController:
        del run_id, query
        return self.server.controller

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


def create_runtime_server(
    workspace: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    run_root: Path | None = None,
    *,
    provider: str = "fake",
    model_name: str | None = None,
    reasoning: dict[str, Any] | None = None,
    stream: bool = True,
    debug_level: int = 0,
    workspace_mode: WorkspaceMode = "current",
    approval_mode: ApprovalMode = "yolo",
    sandbox_mode: SandboxModeInput = "none",
    conversation_root: Path | None = None,
    mcp_clients: Mapping[str, McpClient] | None = None,
    profile: str = "tiny-coder",
    todo_memory_enabled: bool = False,
    memory_enabled: bool = False,
) -> RuntimeHTTPServer:
    resolved_workspace = workspace.expanduser().resolve()
    root = (run_root or resolved_workspace / ".tinyagent" / "runs").expanduser().resolve()
    resolved_conversation_root = (
        conversation_root.expanduser().resolve()
        if conversation_root is not None
        else resolved_workspace / ".tinyagent" / "conversations"
    )
    spec = ProviderSpec(kind=provider, model=model_name, reasoning=reasoning)  # type: ignore[arg-type]
    provider_for(spec, "provider validation")
    controller = RunController(
        RuntimeConfig(
            workspace=resolved_workspace,
            run_root=root,
            provider_factory=lambda task: provider_for(spec, task),
            stream=stream,
            debug_level=debug_level,
            workspace_mode=workspace_mode,
            approval_mode=approval_mode,
            sandbox_mode=sandbox_mode,
            profile=profile,
            conversation_store=ConversationStore(resolved_conversation_root),
            mcp_clients=mcp_clients,
            todo_memory_enabled=todo_memory_enabled,
            memory_enabled=memory_enabled,
        )
    )
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


def _redact_default_surface_data(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_default_surface_data(item)
            for key, item in value.items()
            if key not in DEFAULT_SURFACE_REDACTED_EVENT_DATA_KEYS
        }
    if isinstance(value, list):
        return [_redact_default_surface_data(item) for item in value]
    if isinstance(value, str):
        return DEFAULT_SURFACE_REDACTED_PATH_PATTERN.sub("[redacted]", value)
    return value


def _artifact_hidden_by_default(path: str) -> bool:
    return path.startswith(("artifacts/model-request", "artifacts/model-response", "artifacts/context", "context/"))


def _surface_event_visible(event: Event, debug_level: int) -> bool:
    if event.visibility == "internal":
        return False
    if event.visibility in {"public", "user"}:
        return True
    return event_debug_level(event) <= debug_level


def _surface_event_dict(event: Event, debug_level: int) -> dict[str, Any]:
    payload = event.to_json_dict()
    if debug_level <= 0:
        payload["data"] = _redact_default_surface_data(payload["data"])
    return payload


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


def _not_found_code(message: str) -> str:
    lowered = message.lower()
    if "approval" in lowered:
        return "approval_not_found"
    if "artifact" in lowered:
        return "artifact_not_found"
    if "conversation" in lowered:
        return "conversation_not_found"
    if "run" in lowered:
        return "run_not_found"
    return "not_found"


def _bad_request_code(message: str) -> str:
    lowered = message.lower()
    if "already exists" in lowered:
        return "already_exists"
    if "provider" in lowered:
        return "provider_error"
    if "approval" in lowered:
        return "approval_error"
    if "profile" in lowered:
        return "profile_error"
    return "bad_request"


def _conversation_id_for_run(controller: RunController, run_id: str) -> str:
    store = controller.config.conversation_store
    if store is None:
        return ""
    for conversation in store.list(workspace=controller.config.workspace):
        conversation_id = str(conversation.get("conversation_id") or "")
        if not conversation_id:
            continue
        for turn in store.turns(conversation_id):
            if turn.get("run_id") == run_id:
                return conversation_id
    return ""


def _validate_run_id(run_id: str) -> None:
    validate_run_id(run_id)
