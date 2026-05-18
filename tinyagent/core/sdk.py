"""Small async SDK facade over the synchronous tinyagent kernel."""

from __future__ import annotations

import asyncio
import inspect
import queue
import threading
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from tinyagent.core.contracts import ApprovalHandler, ModelProvider, PolicyEngine, Tool
from tinyagent.core.events import Event, EventSink
from tinyagent.core.hooks import TinyHook
from tinyagent.core.kernel import Kernel
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.run_control import CancelToken
from tinyagent.core.state import ApprovalMode, ApprovalRequest, ApprovalResolution, RunBudgets, RunState
from tinyagent.core.workspace import SandboxModeInput, WorkspaceMode

ApprovalDecision = Literal["approved", "denied", "cancelled", "expired"]
ApprovalScope = Literal["once", "run"]
ApprovalCallback = Callable[[ApprovalRequest, "ApprovalContext"], ApprovalResolution | Awaitable[ApprovalResolution]]

_TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled", "run.timed_out"}
_VALID_APPROVAL_DECISIONS = {"approved", "denied", "cancelled", "expired"}
_VALID_APPROVAL_SCOPES = {None, "once", "run"}


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


class RunHandle:
    def __init__(self, *, run_id: str, sink: _QueueSink, task: asyncio.Task[RunState], cancel_token: CancelToken) -> None:
        self._run_id = run_id
        self._sink = sink
        self._task = task
        self._cancel_token = cancel_token
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
            await self._task
        finally:
            if not self._task.done():
                await self.cancel("event_stream_closed")

    async def cancel(self, reason: str = "user_cancelled") -> None:
        self._cancel_token.cancel(reason)

    async def result(self) -> RunResult:
        state = await self._task
        status = state.terminal_status or state.status
        return RunResult(
            run_id=state.run_id,
            status=status,
            final_output=state.final_output,
            output_dir=state.output_dir,
            events=tuple(state.events),
            failure_reason=state.failure_reason or "",
            cancel_reason=state.cancel_reason or state.cancel_token.reason or "",
        )


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

    @classmethod
    def create(cls, **kwargs) -> Agent:
        return cls(**kwargs)

    async def start(self, prompt: str, *, run_id: str | None = None, output_dir: Path | None = None) -> RunHandle:
        resolved_run_id = run_id or f"run_{uuid4().hex}"
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
        return RunHandle(run_id=resolved_run_id, sink=sink, task=task, cancel_token=cancel_token)

    async def run(self, prompt: str, *, run_id: str | None = None, output_dir: Path | None = None) -> AsyncIterator[Event]:
        handle = await self.start(prompt, run_id=run_id, output_dir=output_dir)
        async for event in handle.events():
            yield event

    async def run_once(self, prompt: str, *, run_id: str | None = None, output_dir: Path | None = None) -> RunResult:
        handle = await self.start(prompt, run_id=run_id, output_dir=output_dir)
        return await handle.result()


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
