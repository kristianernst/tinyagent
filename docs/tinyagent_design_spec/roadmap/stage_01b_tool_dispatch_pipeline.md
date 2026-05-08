# Stage 1b — Tool Dispatch Pipeline

## Problem

`Kernel._dispatch_tool_call()` is the densest method in the core. It handles many guard and execution paths inline:

- unknown tool;
- hidden tool;
- progress guard block;
- policy exception;
- policy decision event;
- hook-returned result;
- hook-mutated call;
- approval resolution;
- policy denial;
- execution start;
- executor errors;
- cancellation;
- after-tool hooks;
- workspace delta;
- transcript and observation recording;
- ContextFS refresh;
- step closure.

This is too much for one method, but a full dispatcher extraction should wait until invariants are tested.

## Target design

Stage 1b has two possible endpoints:

### Minimal endpoint

Keep `_dispatch_tool_call()` in `Kernel`, but extract local helper functions for repeated result construction and ContextFS refresh. Add invariant tests.

### Full endpoint

Extract `ToolDispatcher` only if tests are strong enough.

```python
class ToolDispatcher:
    def dispatch(
        self,
        state: RunState,
        call: ToolCall,
        *,
        visible_tool_names: frozenset[str],
    ) -> None: ...
```

Dependencies:

- tools mapping;
- policy;
- approval resolver;
- executor;
- hook runner;
- progress guard;
- workspace delta observer;
- contextfs refresher;
- index sync callback;
- event recorder helpers.

The full endpoint may be too much for this stage. The recommended first pass is tests and small helpers.

## Dispatch phases

The pipeline should read conceptually as:

1. **Resolve tool** — unknown or hidden tools become synthetic failures.
2. **Progress guard** — repeated no-progress behavior becomes synthetic failure.
3. **Policy** — evaluate and emit policy event.
4. **Before-tool hooks** — may mutate or return synthetic result.
5. **Approval** — resolve if needed.
6. **Permission gate** — deny/block if final decision is not allowed.
7. **Execution envelope** — start mutation/delta/step events.
8. **Run executor** — produce result or convert exceptions/cancel to result.
9. **After-tool hooks** — transform result.
10. **Workspace delta** — compare before/after and emit mutation observations.
11. **Record result** — transcript, observations, tool events.
12. **Refresh context** — update ContextFS.
13. **Close step** — completed, failed, cancelled.

## Tests before extraction

Create tests for each phase:

- unknown tool creates tool result and blocked event;
- hidden tool creates tool result and blocked event;
- progress guard block records result and no executor call;
- policy exception fails run;
- policy denial records blocked result;
- approval denial prevents execution;
- hook-returned `ToolResult` prevents execution;
- hook-mutated call re-evaluates policy;
- executor exception becomes `ToolResult(ok=False)`;
- `RunCancelled` becomes cancelled result and run cancellation;
- successful edit produces workspace delta events;
- non-mutating shell produces no mutation event;
- every dispatch path refreshes ContextFS exactly as expected;
- every started tool step closes.

## Exit criteria

- Dispatch tests exist.
- `_dispatch_tool_call()` is either smaller through helpers or safely extracted.
- Event output remains stable.
- No new abstraction hides policy/approval decisions.

## Why this matters

Tool dispatch is where safety, model intent, and external side effects meet. It should be explicit, but not tangled. The desired result is a readable safety pipeline, not a generic middleware stack.
