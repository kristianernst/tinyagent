"""Small async SDK facade over the synchronous tinyagent kernel."""

from __future__ import annotations

import asyncio
import inspect
import json
import queue
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from tinyagent.core.contracts import ApprovalHandler, ModelProvider, PolicyEngine, Tool
from tinyagent.core.events import Event, EventSink
from tinyagent.core.hooks import TinyHook
from tinyagent.core.ids import validate_run_id
from tinyagent.core.kernel import Kernel
from tinyagent.core.path_safety import checked_relative_path
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.run_control import CancelToken
from tinyagent.core.state import ApprovalMode, ApprovalRequest, ApprovalResolution, RunBudgets, RunState
from tinyagent.core.workspace import SandboxModeInput, WorkspaceMode
from tinyagent.runtime.replay import load_run_events
from tinyagent.runtime.run_record import load_run_record

ApprovalDecision = Literal["approved", "denied", "cancelled", "expired"]
ApprovalScope = Literal["once", "run"]
ApprovalCallback = Callable[[ApprovalRequest, "ApprovalContext"], ApprovalResolution | Awaitable[ApprovalResolution]]

_TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled", "run.timed_out"}
_VALID_APPROVAL_DECISIONS = {"approved", "denied", "cancelled", "expired"}
_VALID_APPROVAL_SCOPES = {None, "once", "run"}
_AGENT_FEATURES = frozenset({"prompt", "start", "run", "run_once", "list_runs", "read_run"})
_RUN_HANDLE_FEATURES = frozenset({"events", "stream", "wait", "result", "cancel"})
_UNSUPPORTED_REASONS = {
    "resume": "run resume is not implemented yet; use read_run() for recorded runs",
    "mcp_status": "MCP status is extension-specific and is not exposed by the base SDK",
}


class SDKError(RuntimeError):
    phase = "sdk"


class SDKRunError(SDKError):
    phase = "run"

    def __init__(self, run_id: str, reason: str) -> None:
        self.run_id = run_id
        super().__init__(f"SDK run failed before producing RunState ({run_id}): {reason}")


class UnsupportedOperationError(SDKError):
    phase = "unsupported"

    def __init__(self, operation: str, reason: str) -> None:
        self.operation = operation
        self.reason = reason
        super().__init__(f"{operation} is not supported: {reason}")


@dataclass(frozen=True)
class ApprovalContext:
    run_id: str
    turn_id: str | None
    workspace: Path
    original_workspace: Path
    current_step_id: str | None
    cancel_reason: str = ""


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    final_output: str
    output_dir: Path
    events: tuple[Event, ...]
    failure_reason: str = ""
    cancel_reason: str = ""
    artifact_paths: tuple[str, ...] = ()
    context_usage: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    output_dir: Path
    task: str = ""
    failure_reason: str = ""


class RunHandle:
    def __init__(
        self,
        *,
        run_id: str,
        sink: _QueueSink,
        task: asyncio.Task[RunState],
        cancel_token: CancelToken,
        capabilities: frozenset[str],
    ) -> None:
        self._run_id = run_id
        self._sink = sink
        self._task = task
        self._cancel_token = cancel_token
        self._capabilities = capabilities
        self._events_started = False

    @property
    def run_id(self) -> str:
        return self._run_id

    async def events(self) -> AsyncIterator[Event]:
        if self._events_started:
            raise RuntimeError("RunHandle.events() is single-consumer; call result() for the completed event tuple.")
        self._events_started = True
        try:
            while True:
                if self._task.done() and self._sink.empty():
                    break
                try:
                    event = await asyncio.to_thread(self._sink.get, 0.05)
                except queue.Empty:
                    continue
                yield event
                if event.type in _TERMINAL_EVENTS and self._sink.empty():
                    break
            await self._state()
        finally:
            if not self._task.done():
                await self.cancel("event_stream_closed")

    async def stream(self) -> AsyncIterator[Event]:
        async for event in self.events():
            yield event

    async def cancel(self, reason: str = "user_cancelled") -> None:
        self._cancel_token.cancel(reason)

    async def result(self) -> RunResult:
        state = await self._state()
        return _result_from_state(state)

    async def wait(self) -> RunResult:
        return await self.result()

    def supports(self, feature: str) -> bool:
        return feature in self._capabilities

    async def _state(self) -> RunState:
        try:
            return await self._task
        except Exception as exc:
            raise SDKRunError(self._run_id, str(exc)) from exc


class Agent:
    def __init__(
        self,
        *,
        workspace: str | Path,
        provider: ModelProvider,
        profile=None,
        tools: Sequence[Tool],
        policy: PolicyEngine,
        hooks: Sequence[TinyHook] = (),
        budgets: RunBudgets | None = None,
        workspace_mode: WorkspaceMode = "auto",
        approval_mode: ApprovalMode = "yolo",
        sandbox_mode: SandboxModeInput = "none",
        approval_handler: ApprovalCallback | ApprovalHandler | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.provider = provider
        self.profile = profile or ApexCoderProfile()
        self.tools = list(tools)
        self.policy = policy
        self.hooks = tuple(hooks)
        self.budgets = budgets
        self.workspace_mode = workspace_mode
        self.approval_mode = approval_mode
        self.sandbox_mode = sandbox_mode
        self.approval_handler = approval_handler
        self._capabilities = _agent_capabilities_for(approval_handler)

    @classmethod
    def create(cls, **kwargs) -> Agent:
        return cls(**kwargs)

    async def start(self, prompt: str, *, run_id: str | None = None, output_dir: Path | None = None) -> RunHandle:
        resolved_run_id = run_id or f"run_{uuid4().hex}"
        validate_run_id(resolved_run_id)
        sink = _QueueSink()
        cancel_token = CancelToken()
        loop = asyncio.get_running_loop()
        approval_handler = _approval_handler_adapter(self.approval_handler, loop=loop, cancel_token=cancel_token)
        kernel = Kernel(
            model=self.provider,
            profile=self.profile,
            tools=self.tools,
            policy=self.policy,
            hooks=self.hooks,
            budgets=self.budgets,
            approval_handler=approval_handler,
            event_sink=sink,
            workspace_mode=self.workspace_mode,
            approval_mode=self.approval_mode,
            sandbox_mode=self.sandbox_mode,
        )
        task = asyncio.create_task(
            asyncio.to_thread(
                kernel.run,
                prompt,
                workspace=self.workspace,
                run_id=resolved_run_id,
                output_dir=output_dir,
                cancel_token=cancel_token,
                workspace_mode=self.workspace_mode,
                approval_mode=self.approval_mode,
                sandbox_mode=self.sandbox_mode,
            )
        )
        return RunHandle(
            run_id=resolved_run_id,
            sink=sink,
            task=task,
            cancel_token=cancel_token,
            capabilities=_RUN_HANDLE_FEATURES,
        )

    async def run(self, prompt: str, *, run_id: str | None = None, output_dir: Path | None = None) -> AsyncIterator[Event]:
        handle = await self.start(prompt, run_id=run_id, output_dir=output_dir)
        async for event in handle.events():
            yield event

    async def run_once(self, prompt: str, *, run_id: str | None = None, output_dir: Path | None = None) -> RunResult:
        handle = await self.start(prompt, run_id=run_id, output_dir=output_dir)
        return await handle.result()

    async def prompt(self, prompt: str, *, run_id: str | None = None, output_dir: Path | None = None) -> RunResult:
        return await self.run_once(prompt, run_id=run_id, output_dir=output_dir)

    def supports(self, feature: str) -> bool:
        return feature in self._capabilities

    def support_reason(self, feature: str) -> str:
        if self.supports(feature):
            return "supported"
        return _UNSUPPORTED_REASONS.get(feature, "unsupported by the base SDK")

    def list_runs(self) -> tuple[RunSummary, ...]:
        root = self._runs_root()
        if not root.exists():
            return ()
        summaries: list[RunSummary] = []
        for path in sorted(root.iterdir()):
            if path.is_symlink() or not path.is_dir():
                continue
            if not _path_is_relative_to(path.resolve(), root):
                continue
            if not (path / "events.jsonl").exists():
                continue
            try:
                record = load_run_record(path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            summaries.append(
                RunSummary(
                    run_id=record.run_id,
                    status=record.status,
                    output_dir=path,
                    task=record.task,
                    failure_reason=record.failure_reason,
                )
            )
        return tuple(summaries)

    def read_run(self, run_id: str) -> RunResult:
        path = self._run_path(run_id)
        record = load_run_record(path)
        events = tuple(load_run_events(path))
        metrics = _read_json(path / "metrics.json")
        return RunResult(
            run_id=record.run_id,
            status=record.status,
            final_output=_read_final_output(_run_file(path, record.final_output_path)),
            output_dir=path,
            events=events,
            failure_reason=record.failure_reason,
            cancel_reason=str(metrics.get("cancel_reason") or ""),
            artifact_paths=_artifact_paths(events),
            context_usage=_context_usage_from_metrics(metrics),
        )

    async def resume(self, run_id: str) -> RunHandle:
        del run_id
        raise UnsupportedOperationError("resume", self.support_reason("resume"))

    def _runs_root(self) -> Path:
        root = self.workspace.expanduser().resolve() / ".tinyagent" / "runs"
        if _path_has_existing_symlink(root):
            raise ValueError(f"SDK runs root crosses a symlink: {root}")
        return root.resolve()

    def _run_path(self, run_id: str) -> Path:
        validate_run_id(run_id)
        root = self._runs_root()
        path = root / run_id
        if path.exists():
            if path.is_symlink():
                raise ValueError(f"SDK run directory crosses a symlink: {run_id}")
            if not _path_is_relative_to(path.resolve(), root):
                raise ValueError(f"SDK run directory is outside runs root: {run_id}")
        return path


def _agent_capabilities_for(approval_handler: ApprovalCallback | ApprovalHandler | None) -> frozenset[str]:
    features = set(_AGENT_FEATURES)
    if approval_handler is not None:
        features.add("approvals")
    return frozenset(features)


def _result_from_state(state: RunState) -> RunResult:
    status = state.terminal_status or state.status
    events = tuple(state.events)
    return RunResult(
        run_id=state.run_id,
        status=status,
        final_output=state.final_output,
        output_dir=state.output_dir,
        events=events,
        failure_reason=state.failure_reason or "",
        cancel_reason=state.cancel_reason or state.cancel_token.reason or "",
        artifact_paths=_artifact_paths(events),
        context_usage={
            "context_token_estimate": state.context_token_estimate,
            "compaction_count": state.compaction_count,
            "context_checkpoint_artifact": state.context_checkpoint_artifact or "",
        },
    )


def _artifact_paths(events: Sequence[Event]) -> tuple[str, ...]:
    paths: list[str] = []
    for event in events:
        if event.type != "artifact.created":
            continue
        path = event.data.get("path")
        if isinstance(path, str) and path:
            paths.append(path)
    return tuple(paths)


def _context_usage_from_metrics(metrics: dict[str, Any]) -> dict[str, object]:
    return {
        "context_token_estimate": int(metrics.get("context_token_estimate") or 0),
        "compaction_count": int(metrics.get("compaction_count") or 0),
        "context_checkpoint_artifact": str(metrics.get("context_checkpoint_artifact") or ""),
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_file(run_dir: Path, value: str) -> Path:
    rel = checked_relative_path(value, label="Run artifact path")
    target = (run_dir / rel).resolve()
    if not _path_is_relative_to(target, run_dir):
        raise ValueError(f"Run artifact path is outside run directory: {value}")
    return target


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _path_has_existing_symlink(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _read_final_output(path: Path) -> str:
    try:
        text = path.read_text()
    except OSError:
        return ""
    prefix = "# Final output\n\n"
    if text.startswith(prefix):
        return text.removeprefix(prefix).rstrip("\n")
    return text


class AsyncApprovalHandlerAdapter:
    def __init__(
        self,
        callback: ApprovalCallback,
        *,
        loop: asyncio.AbstractEventLoop,
        cancel_token: CancelToken,
        poll_seconds: float = 0.05,
    ) -> None:
        self._callback = callback
        self._loop = loop
        self._cancel_token = cancel_token
        self._poll_seconds = poll_seconds

    def resolve(self, request: ApprovalRequest, state: RunState) -> ApprovalResolution:
        if self._cancel_token.cancelled or state.cancel_token.cancelled:
            return ApprovalResolution(
                approval_id=request.approval_id,
                decision="cancelled",
                reason=self._cancel_token.reason or state.cancel_token.reason or "cancelled",
            )
        context = ApprovalContext(
            run_id=state.run_id,
            turn_id=state.current_turn_id,
            workspace=state.workspace.root,
            original_workspace=(state.workspace_envelope.original_root if state.workspace_envelope is not None else state.workspace.root),
            current_step_id=state.current_step_id,
            cancel_reason=state.cancel_token.reason or self._cancel_token.reason or "",
        )
        future = asyncio.run_coroutine_threadsafe(self._invoke(request, context), self._loop)
        while True:
            if self._cancel_token.cancelled or state.cancel_token.cancelled:
                future.cancel()
                return ApprovalResolution(
                    approval_id=request.approval_id,
                    decision="cancelled",
                    reason=self._cancel_token.reason or state.cancel_token.reason or "cancelled",
                )
            try:
                return _normalize_approval_resolution(future.result(timeout=self._poll_seconds), request)
            except TimeoutError:
                continue

    async def _invoke(self, request: ApprovalRequest, context: ApprovalContext) -> ApprovalResolution:
        result = self._callback(request, context)
        if inspect.isawaitable(result):
            return await result
        return result


class _SyncApprovalHandlerAdapter:
    def __init__(self, callback: ApprovalCallback) -> None:
        self._callback = callback

    def resolve(self, request: ApprovalRequest, state: RunState) -> ApprovalResolution:
        context = ApprovalContext(
            run_id=state.run_id,
            turn_id=state.current_turn_id,
            workspace=state.workspace.root,
            original_workspace=(state.workspace_envelope.original_root if state.workspace_envelope is not None else state.workspace.root),
            current_step_id=state.current_step_id,
            cancel_reason=state.cancel_token.reason or "",
        )
        result = self._callback(request, context)
        if inspect.isawaitable(result):
            raise RuntimeError("async approval callback requires Agent.start() from an active event loop")
        return _normalize_approval_resolution(result, request)


def _approval_handler_adapter(
    handler: ApprovalCallback | ApprovalHandler | None,
    *,
    loop: asyncio.AbstractEventLoop,
    cancel_token: CancelToken,
) -> ApprovalHandler | None:
    if handler is None:
        return None
    resolve = getattr(handler, "resolve", None)
    if callable(resolve):
        return handler  # type: ignore[return-value]
    return AsyncApprovalHandlerAdapter(handler, loop=loop, cancel_token=cancel_token)


def _normalize_approval_resolution(result: ApprovalResolution, request: ApprovalRequest) -> ApprovalResolution:
    if not isinstance(result, ApprovalResolution):
        raise TypeError("approval callback must return ApprovalResolution")
    if result.decision not in _VALID_APPROVAL_DECISIONS:
        raise ValueError(f"invalid approval decision: {result.decision}")
    if result.scope not in _VALID_APPROVAL_SCOPES:
        raise ValueError(f"invalid approval scope: {result.scope}")
    return ApprovalResolution(
        approval_id=request.approval_id,
        decision=result.decision,
        scope=result.scope,
        reason=result.reason,
    )


class _QueueSink(EventSink):
    def __init__(self) -> None:
        self._queue: queue.Queue[Event] = queue.Queue()
        self._terminal_seen = threading.Event()

    def emit(self, event: Event) -> None:
        self._queue.put(event)
        if event.type in _TERMINAL_EVENTS:
            self._terminal_seen.set()

    def get(self, timeout: float) -> Event:
        return self._queue.get(timeout=timeout)

    def empty(self) -> bool:
        return self._queue.empty()
