# Stage 1c — Event Contract Tests

## Problem

Tinyagent’s event stream is the product contract for replay, evals, SDK clients, runtime UI, and debugging. Refactors to `Kernel`, ContextFS, routing, or SDK can silently change event order or payloads.

## Target design

Create an event invariant test suite that is independent of implementation structure.

Potential file:

```text
tests/core/test_event_contract.py
```

or:

```text
tinyagent/evals/invariants.py
```

The invariant checker should accept a list of events and return failures.

```python
def check_event_invariants(events: Sequence[Event]) -> list[str]: ...
```

## Invariants

### Sequence invariants

- `seq` is strictly increasing.
- Every durable event has `durability == "event_log"`.
- Every ephemeral event is absent from `events.jsonl` but may appear in live sink tests.
- Terminal run event appears at most once.

### Run/turn invariants

- `run.started` appears before any model/tool events.
- If `turn.started` appears, exactly one matching terminal turn event appears.
- Terminal turn status matches run status where applicable.

### Step invariants

- Every `step.started` has a matching step terminal event before the next terminal run event.
- No current step remains after terminal run.
- Approval wait steps close.
- Artifact finalization step closes.

### Model invariants

- `model.call.started` precedes `model.call.completed` or failure/cancel/timeout for that call index.
- `model.tool_call.assembly.completed` appears before dispatch of that tool call unless streamed assembly already emitted equivalent event.
- Model response artifact is created or explicitly absent according to provider behavior.

### Tool invariants

- Every tool call has exactly one transcript tool result.
- Policy evaluation occurs before execution for visible known tools.
- `tool.execution.started` precedes completed/failed/cancelled unless synthetic blocked result.
- `tool.execution.blocked` has a corresponding failed/synthetic result.

### Artifact invariants

- `artifact.created` paths do not escape run output.
- Hidden artifacts are not in public listings.
- Every artifact ref in public events is safe or redacted according to visibility.

### Workspace invariants

- Mutation events occur only for mutating tools or shell mutation detection.
- `workspace.delta.started` has `workspace.delta.completed`.
- If `workspace.mutation.detected`, changed paths are inside workspace and not hidden.

## Snapshot tests

In addition to invariants, keep small event snapshots for key flows:

- fake no-tool final response;
- fake read-file/shell run;
- edit then diff/test finalization;
- policy-denied shell;
- approval-required shell;
- cancelled shell;
- hook-transformed run;
- ContextFS compaction run.

Snapshots should compare event types and selected stable fields, not full timestamps/IDs.

## Exit criteria

- Event invariant checker exists.
- Invariant tests run in normal test suite.
- Refactors in Stage 1 and Stage 2 use these tests.
- Event changes require explicit fixture updates.

## Why this is part of Kernel cleanup

A lean kernel is only valuable if its behavior remains inspectable. Event tests let you simplify code without losing the trace contract.
