# Stage 4a — Cancellable SDK Run Handle

## Problem

`Agent.run()` currently runs `kernel.run` in a background thread via `asyncio.to_thread()` and yields events from a queue. If the async task/generator is cancelled, the underlying kernel thread may continue because no caller-controlled `CancelToken` is passed.

## Target design

Introduce `RunHandle`.

```python
class RunHandle:
    async def events(self) -> AsyncIterator[Event]: ...
    async def cancel(self, reason: str = "user_cancelled") -> None: ...
    async def result(self) -> RunResult: ...
    @property
    def run_id(self) -> str: ...
```

`Agent.start()` returns a handle.

```python
run = await agent.start(prompt)
```

`Agent.run()` can remain as a compatibility wrapper around `start().events()`.

## Implementation details

- Create a `CancelToken` before starting `kernel.run`.
- Pass the token to `kernel.run`.
- Store the thread task/future inside `RunHandle`.
- `RunHandle.cancel()` calls `token.cancel(reason)`.
- If event iteration exits early, optionally cancel depending on API semantics.
- `RunHandle.result()` awaits thread completion and returns structured result.

## Result type

```python
@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    final_output: str
    output_dir: Path
    events: tuple[Event, ...]
    failure_reason: str = ""
    cancel_reason: str = ""
```

## Event queue behavior

Keep `_QueueSink`, but add terminal detection:

- event iterator exits after terminal run event and queue drain;
- `result()` waits for the kernel task;
- if kernel raises unexpectedly, result reports failure or re-raises according to SDK policy.

## Tests

- Start a fake long shell run; call `cancel`; assert run cancelled and thread completes.
- Event iterator ends after terminal event.
- `result()` returns final output for successful fake run.
- Early event iterator close does not leak thread if API says close cancels.
- Multiple calls to `cancel()` are idempotent.

## Exit criteria

- SDK users can cancel runs reliably.
- Underlying `CancelToken` is shared with kernel.
- Existing `Agent.run()` compatibility remains or is clearly migrated.

## Why this matters

A serious SDK must model an agent run as a long-running action with events, cancellation, and result. This mirrors ROS actions and modern agent SDK expectations.
