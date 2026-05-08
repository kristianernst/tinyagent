# Current Tinyagent Findings From Code Export

This appendix lists concrete findings from the provided export. These are the repo-level facts that drive the roadmap.

## Strengths

### Explicit state and event boundary

`RunState.emit()` is a strong primitive. It enforces ordered event emission, durable vs ephemeral events, visibility, artifact references, JSONL persistence, and stream-sink delivery. This is the right center of the runtime.

### Event vocabulary is comprehensive

The event taxonomy already covers run, turn, step, workspace, model, tool, command, policy, approval, context, index, skill, extension, artifact, and cancellation events. That is enough to support runtime servers, replay, evals, and product UI.

### ContextFS is strategically aligned

The repo already writes task, environment, status, diff, failures, observations, transcript, history, raw event snapshots, tool docs, diff docs, and todo memory into a bounded file surface. This is aligned with dynamic context discovery patterns.

### Policy is real, not decorative

The local policy denies or gates network-looking commands, protected `.tinyagent` writes, run-artifact writes, secret-ish env files, workspace escapes, risky commands, dirty workspace mutation, and repeated failed commands. It has approval and permission metadata.

### Workspace delta capture is valuable

`WorkspaceDeltaObserver` snapshots before/after tool calls and captures changed paths and diff artifacts. This is important for finish gates, evals, and user trust.

### Evals are harness-aware

The eval metrics inspect event logs for policy denials, finish gates, repeated commands, context usage, search/code/skill/MCP counts, verification-after-edit, and diff-after-edit. This is exactly the direction needed.

## Main problems

### `Kernel` has too many local responsibilities

The current `Kernel` owns:

- extension host construction;
- skill/context registry construction;
- workspace preparation;
- run lifecycle;
- context building;
- compaction;
- hook execution;
- model call tracing;
- model request/response artifacts;
- visible tool checks;
- progress guard;
- policy evaluation;
- approval resolution;
- tool execution;
- workspace delta capture;
- index sync;
- observations;
- ContextFS refresh;
- finish gate;
- artifact finalization.

This is the main maintainability issue.

### Hook execution is duplicated

The same event/error pattern appears in:

- `_run_hooks`;
- `_on_context`;
- `_after_model_response`;
- `_before_model_call`;
- `_before_tool_call`;
- `_after_tool_result`;
- `_before_finish`.

A `HookRunner` can remove this without changing behavior.

### `_dispatch_tool_call` has too many exits

It handles unknown tools, hidden tools, progress blocks, policy exceptions, hook-returned results, hook-mutated calls, approval, policy denial, execution, cancellation, workspace delta, step closure, and ContextFS refresh in one method.

This should be cleaned after hook extraction and event invariants.

### ContextFS mixes rendering and safety

`contextfs.py` includes rendering, path resolution, artifact allowlists, git diff/status, transcript/observation formatting, sanitization, and index generation. The rendering part should become a plan. The safety/path functions should remain explicit.

### Legacy artifact route likely exposes hidden artifacts

`RunController.artifacts()` hides internal artifacts from listing and `public_artifact_path()` rejects hidden artifacts. But the base route `_artifact()` calls `controller.store.artifact_path()` directly, not `public_artifact_path()`. This should be fixed and tested for both legacy and v1 routes.

### Approval handler exception can leave stale current step

In `_resolve_approval`, when `approval_handler.resolve()` raises a non-cancellation exception, a denied resolution is created but the approval wait step is not clearly closed. This can leave stale `current_step_kind/current_step_id` state. Add step-closure tests.

### SDK cancellation is insufficient

`Agent.run()` starts `kernel.run` in a thread but does not pass a `CancelToken` controlled by the async generator. Cancelling the async task does not necessarily stop the thread. This should be fixed by a run handle and cancellation token.

### Product/runtime route duplication creates drift

`RuntimeHandler` and `ProductRuntimeHandler` duplicate many routes and event/artifact behaviors. This creates inconsistent safety behavior. A shared route implementation with resolver injection is safer.

## Design-sensitive risks

### Over-refactoring Kernel

A full state-machine or graph refactor would add conceptual weight and risk event regressions. Extract narrow seams first.

### Over-abstracting ContextFS

A virtual filesystem abstraction would conflict with the desired file-first philosophy. Use a render plan, not a new filesystem layer.

### Making all features default

MCP, LSP, todo memory, semantic search, subagents, and self-improvement are all useful. Making them default would violate the Pi/tinygrad-like design goal. They should be extension/profile/product features.

## Recommended first PR sequence

1. Artifact exposure tests and fix.
2. Approval step closure tests and fix.
3. ContextFS stable refs / oversize search tests and fix.
4. HookRunner extraction with event snapshot tests.
5. ContextFS render-plan extraction with file snapshot tests.
6. `tiny-pi` profile and profile comparison evals.
