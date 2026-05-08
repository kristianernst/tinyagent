# Stage 5a — Event Invariant Tests

## Problem

Event output is central to replay, evals, product UI, SDK, and trust. It needs a reusable invariant checker, not only ad hoc unit assertions.

## Target design

Add:

```python
def check_event_invariants(events: Sequence[Event]) -> list[str]: ...
```

Potential module:

```text
tinyagent/evals/invariants.py
```

or:

```text
tinyagent/runtime/invariants.py
```

Use it in tests and eval reports.

## Core invariants

- monotonic sequence;
- exactly one terminal event if run completed;
- no unclosed turns;
- no unclosed steps;
- policy before execution;
- tool call/result pairing;
- workspace delta start/completed pairing;
- approval request/resolution pairing;
- artifact paths do not escape run output;
- public event redaction at debug level 0;
- finalization attempted event sequence.

## Test fixtures

Use fake providers for deterministic runs:

1. final response only;
2. read file then final;
3. patch then diff/test then final;
4. policy denial;
5. approval required;
6. cancellation during shell;
7. hook failure;
8. compaction path.

## Exit criteria

- Invariant checker catches known artificial violations.
- Normal fake runs pass.
- Eval reports can include invariant failures.

## Why this matters

A traceable harness lives or dies by its trace contract. Invariants are the cheapest way to protect that contract.
