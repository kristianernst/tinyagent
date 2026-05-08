# Stage 1 — Lean Kernel Boundary

## Goal

Make `Kernel` smaller and easier to reason about while preserving the explicit run loop and event semantics.

## Why this is necessary

The current `Kernel` is explicit but too broad. It contains repeated hook logic, many tool-dispatch branches, model call tracing, context build events, compaction, finalization, workspace mutation handling, index sync, approvals, and observations. This creates friction for future extension work and increases the risk of event drift.

Stage 1 should not rewrite the loop. It should extract only narrow, behavior-preserving seams.

## Substages

1. `stage_01a_hook_runner.md`
2. `stage_01b_tool_dispatch_pipeline.md`
3. `stage_01c_event_contract_tests.md`

## Primary changes

- Add `tinyagent/core/hook_runner.py`.
- Move hook start/completed/failed event emission and error policy into `HookRunner`.
- Replace the repeated hook loops in `Kernel` with calls to `HookRunner`.
- Add event snapshots for hook behavior.
- Add tool-dispatch invariants and optional preparatory helpers, but do not fully extract dispatch until tests are strong.

## Recommended sequencing

### PR 1: tests around existing hook behavior

Before extraction, write tests for:

- `on_run_start` success;
- `on_context` transform;
- `before_model_call` transform pair;
- `after_model_response` transform;
- `before_tool_call` returns `ToolResult`;
- `before_tool_call` mutates `ToolCall`;
- `after_tool_result` transform;
- `before_finish` transform;
- hook exception with `hook_error_policy="fail"`;
- hook exception with `hook_error_policy="record"`.

### PR 2: implement HookRunner

Keep exact event payloads where possible. Do not optimize payloads or naming in this PR.

### PR 3: remove Kernel hook methods or delegate them

Replace the body of existing hook methods with `HookRunner` calls, or delete them if call sites are updated.

### PR 4: dispatch invariants

Add tests around unknown tools, invisible tools, progress guard, policy denial, approval denial, execution exception, cancellation, mutation, and ContextFS refresh.

Only after PR 4 should optional dispatcher extraction be considered.

## Exit criteria

- `Kernel` no longer contains repeated hook loops.
- Hook event snapshots pass before and after extraction.
- `Kernel` remains readable and still owns the high-level loop.
- No event output changes except intentionally documented ones from Stage 0.
- Tool-dispatch invariant tests exist.

## Risks

### Risk: HookRunner becomes a framework

Prevent by keeping it ignorant of model/tool semantics. It only calls hook methods and emits hook events.

### Risk: event output changes silently

Prevent with snapshot tests.

### Risk: tool dispatch extraction happens too early

Prevent by making Stage 1b mostly test/invariant-oriented unless the extraction is obviously mechanical.
