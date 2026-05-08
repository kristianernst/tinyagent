# Stage 4b — Approval Callback API

## Problem

Tinyagent has `ApprovalHandler` in the core and an HTTP `ApprovalBroker` in the runtime, but the SDK does not expose approvals. SDK users cannot build human-in-the-loop workflows without dropping to runtime server APIs.

## Target design

Support approval callbacks in SDK:

```python
async def approve(request: ApprovalRequest, state: ApprovalContext) -> ApprovalResolution:
    ...

agent = Agent(..., approval_handler=approve)
```

Or support an approval queue:

```python
run = await agent.start(...)
async for approval in run.approvals():
    await approval.resolve("approved", scope="once")
```

Start with callback; queue can be added later.

## Bridge sync/async

`Kernel` expects synchronous `ApprovalHandler.resolve`. SDK runs in a thread. To support async callbacks:

- create an adapter that submits the coroutine to the event loop with `asyncio.run_coroutine_threadsafe`;
- wait for result in the kernel thread;
- respect cancellation.

```python
class AsyncApprovalHandlerAdapter:
    def resolve(self, request: ApprovalRequest, state: RunState) -> ApprovalResolution:
        future = asyncio.run_coroutine_threadsafe(callback(request, context), loop)
        return future.result(timeout=...)
```

If callback raises, follow Stage 0b behavior: denied resolution and step failure.

## Approval context

Do not pass full mutable `RunState` to external SDK callbacks unless necessary. Provide a small immutable context:

```python
@dataclass(frozen=True)
class ApprovalContext:
    run_id: str
    turn_id: str | None
    workspace: Path
    current_step_id: str | None
```

## Tests

- Async callback approves; tool executes.
- Async callback denies; tool blocked.
- Callback raises; approval denied and step closes.
- Callback is cancelled; run cancels or approval denied according to chosen semantics.
- SDK cancellation while waiting for approval unblocks the handler.

## Exit criteria

- SDK can resolve approvals without HTTP server.
- Approval behavior matches runtime broker semantics.
- Approval wait step invariants hold.

## Why this matters

Human review is a core agent SDK capability. Tinyagent already has the internal primitive; Stage 4b exposes it cleanly without product bloat.
