"""Small async SDK facade over the synchronous tinyagent kernel."""

from __future__ import annotations

import asyncio
import queue
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

from agentd.contracts import ModelProvider, PolicyEngine, Tool
from agentd.events import Event, EventSink
from agentd.hooks import TinyHook
from agentd.kernel import Kernel
from agentd.profiles import ApexCoderProfile
from agentd.state import ApprovalMode, RunBudgets
from agentd.workspace import SandboxModeInput, WorkspaceMode


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

    @classmethod
    def create(cls, **kwargs) -> "Agent":
        return cls(**kwargs)

    async def run(self, prompt: str, *, run_id: str | None = None, output_dir: Path | None = None) -> AsyncIterator[Event]:
        sink = _QueueSink()
        kernel = Kernel(
            model=self.provider,
            profile=self.profile,
            tools=self.tools,
            policy=self.policy,
            hooks=self.hooks,
            budgets=self.budgets,
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
                run_id=run_id,
                output_dir=output_dir,
                workspace_mode=self.workspace_mode,
                approval_mode=self.approval_mode,
                sandbox_mode=self.sandbox_mode,
            )
        )
        try:
            while True:
                if task.done() and sink.empty():
                    break
                try:
                    event = await asyncio.to_thread(sink.get, 0.05)
                except queue.Empty:
                    continue
                yield event
            await task
        finally:
            if not task.done():
                task.cancel()

class _QueueSink(EventSink):
    def __init__(self) -> None:
        self._queue: queue.Queue[Event] = queue.Queue()

    def emit(self, event: Event) -> None:
        self._queue.put(event)

    def get(self, timeout: float) -> Event:
        return self._queue.get(timeout=timeout)

    def empty(self) -> bool:
        return self._queue.empty()
