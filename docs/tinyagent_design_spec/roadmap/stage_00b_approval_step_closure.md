# Stage 0b — Approval Step Closure

## Problem

`Kernel._resolve_approval()` starts an `approval_wait` step when an approval handler exists. If `approval_handler.resolve()` raises a non-cancellation exception, the code constructs a denied `ApprovalResolution`, but the current step may not be closed. This can leave stale `current_step_kind`, `current_step_id`, and `current_model_call_id` state.

## Target behavior

Every started step must close exactly once with one of:

- `step.completed`;
- `step.failed`;
- `step.cancelled`;
- `step.timeout`;
- `step.idle_timeout`.

Approval-specific cases:

| Case | Step status | Approval resolution |
| --- | --- | --- |
| User approves | completed | approved |
| User denies | completed | denied |
| Handler unavailable | no step started if no handler | denied |
| Handler raises | failed or completed with denied; choose one and test | denied |
| Run cancelled while waiting | cancelled | cancelled |

Recommendation: if handler raises, emit `step.failed` with the reason and return a denied resolution. This makes the trace honest.

## Code changes

In `_resolve_approval()`:

```python
state.start_step("approval_wait", ...)
try:
    resolution = self.approval_handler.resolve(approval, state)
except RunCancelled:
    state.finish_step("cancelled", data={...})
    raise
except Exception as exc:
    resolution = ApprovalResolution(... denied ...)
    state.finish_step("failed", data={"approval_id": ..., "reason": str(exc)})
else:
    state.finish_step("completed", data={"approval_id": ..., "decision": resolution.decision})
```

Guard against double-closing if future code changes.

## Tests

### Unit test: handler exception

Use a fake `ApprovalHandler` that raises `RuntimeError("boom")`.

Expected:

- `approval.requested` emitted;
- `step.started` for approval wait emitted;
- `step.failed` emitted;
- `approval.resolved` emitted with `decision=denied` and reason containing handler error;
- tool call denied and not executed;
- `state.current_step_kind is None` after run;
- terminal run event exists.

### Unit test: handler approval

Fake handler returns approved.

Expected:

- `step.completed` for approval wait;
- approval resolved approved;
- tool executes if policy allows after approval.

### Unit test: cancellation while waiting

Fake handler blocks until cancel token is triggered.

Expected:

- `step.cancelled`;
- `approval.resolved` or run cancellation path consistent with current behavior;
- no stale current step.

## Event contract

This may add a `step.failed` event in a path where previously no closure event existed. That is a correctness improvement. Snapshot tests should record the new behavior.

## Exit criteria

- No approval wait path leaves current step set.
- Step closure tests pass.
- Approval denial caused by handler exception is visible in trace.

## Why this matters for minimalism

Minimal systems rely on invariants. “Every step closes” is a simple invariant that makes replay, inspection, SDK behavior, and product UI easier. It is better than adding special cases later.
