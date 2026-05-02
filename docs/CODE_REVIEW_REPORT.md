# Tinyagent Code Review Report

Date: 2026-04-25
Current branch: `bra-9-model-providers`

This report summarizes the current Tinyagent design and implementation for external review. It covers the intended architecture, what has been built so far, what is deliberately not built yet, and the areas where reviewer scrutiny would be most valuable.

## Executive Summary

Tinyagent is a minimal general-purpose agent harness. The design target is not a broad framework; it is a small, inspectable runtime that can execute an agent loop, record replayable traces, dispatch tools through policy, and evolve capability mostly through profiles rather than kernel complexity.

The current implementation covers the early Milestone 0 foundation:

- Python project scaffold and `agentctl` CLI placeholder.
- Minimal kernel loop.
- Explicit runtime state and event records.
- Profile, model, tool, policy, and executor contracts.
- Run output writer for `events.jsonl`, `summary.md`, `metrics.json`, `final.diff`, and model artifacts.
- Exact model context/request/response artifacts for each model call.
- Deterministic fake provider.
- OpenAI-compatible chat-completions provider using only the Python standard library.
- Focused pytest coverage for scaffold, kernel loop, trace artifacts, and provider behavior.

The codebase is intentionally small: the current Python runtime is about 810 lines across `agentd/` and `agentctl/`, with about 486 lines of tests. That is already enough to expose the architectural shape without hiding behavior behind framework machinery.

## Guiding Design Philosophy

The repository now includes two design discipline documents:

- `docs/PHILOSOPHY.md`
- `docs/MERGE.md`

The core principles are:

- Few concepts, few files, low ceremony.
- Explicit state.
- Replayable behavior.
- Strong defaults.
- Bounded YOLO.
- Deletions over abstractions.
- Kernel remains boring; profile owns behavior.
- Event log is the source of truth.
- Claims about capability, speed, or behavior need tests, traces, evals, or benchmarks.

The merge checklist is intentionally hostile to premature abstractions like middleware, graph runners, callback managers, provider routers, plugin managers, and memory stores. Those may become useful later, but they are not justified in Milestone 0.

## Graphite Stack State

Current stack:

```text
bra-9-model-providers             d3602f8 Add model providers
bra-8-run-trace-artifacts         0bb3917 Add run trace artifacts
docs-philosophy-merge-checklist   8cc1ad8 Add tinyagent philosophy and merge checklist
main                              e0470f3 Merge pull request #1
```

Relevant branches:

- `docs-philosophy-merge-checklist`: adds philosophy and merge checklist docs.
- `bra-8-run-trace-artifacts`: adds event taxonomy, JSONL loading, context/model artifacts.
- `bra-9-model-providers`: adds fake and OpenAI-compatible providers.

`main` contains the merged `BRA-7` kernel contracts work.

## Repository Layout

```text
agentctl/
  cli.py                 Minimal CLI placeholder.

agentd/
  contracts.py           Protocols for tools, models, profiles, policy, executor.
  events.py              Event type list, Event record, JSONL loader.
  kernel.py              Minimal event loop.
  models.py              Fake and OpenAI-compatible model providers.
  output.py              Run output and artifact writing.
  state.py               RunState and runtime data records.

docs/
  PHILOSOPHY.md          Code philosophy.
  MERGE.md               Merge/review checklist.

profiles/apex-coder/
  system.md              Placeholder for the default profile.

tests/
  test_cli.py
  test_kernel.py
  test_models.py
  test_scaffold.py
```

## Runtime Architecture

The runtime is organized around five small concepts:

- `RunState`: mutable state for a single run.
- `Event`: append-only trace record.
- `Profile`: builds messages, selects tools, controls finish/continue behavior.
- `ModelProvider`: produces model responses from messages and visible tools.
- `Tool`: executes one model-requested action through policy and executor.

The kernel owns only the loop:

```text
create RunState
log RunStarted
while not done:
  check budgets
  ask profile for messages and visible tools
  write context/request artifacts
  log ModelRequest
  call model provider
  write response artifact
  log ModelResponse
  for each tool call:
    log ToolCallRequested
    evaluate policy
    log PolicyDecision
    if allowed:
      run tool through executor
      log ToolCallFinished
  let profile compact or finish
write run outputs
```

This is intentionally not a workflow engine. There is no graph runner, planner, registry lifecycle, callback manager, or plugin system.

## Implemented Files

### `agentd/state.py`

Defines the core data records:

- `RunBudgets`
- `Workspace`
- `Message`
- `ToolCall`
- `ToolResult`
- `ModelResponse`
- `PolicyDecision`
- `RunState`

`RunState` tracks task, workspace, output directory, budgets, events, tool results, turn/tool counts, completion/failure status, summary, and final diff. It also owns `add_event`, `finish`, and `fail`.

Reviewer notes:

- This file is central and should stay boring.
- The current `RunState` is mutable by design. That keeps the loop simple, but reviewers should consider whether any mutations are too implicit.
- Future additions should be resisted unless they are needed for traceability, safety, or capability.

### `agentd/events.py`

Defines the minimal event taxonomy and event serialization:

- `EVENT_TYPES`
- `Event.to_json_dict`
- `Event.from_json_dict`
- `load_events_jsonl`

Current event taxonomy:

```text
RunStarted
RunFinished
RunFailed
ContextBuilt
ModelRequest
ModelResponse
ToolCallRequested
PolicyDecision
ToolCallStarted
ToolCallFinished
CommandStarted
CommandFinished
PatchApplied
FileRead
SearchCompleted
DiffSnapshot
ArtifactWritten
```

Reviewer notes:

- Event type names are currently strings, not an enum. This is deliberate for low ceremony, but worth reviewing.
- The taxonomy includes future tool events before all tools exist. This prevents each tool issue from inventing event names ad hoc.

### `agentd/contracts.py`

Defines structural protocols:

- `Tool`
- `ModelProvider`
- `Profile`
- `PolicyEngine`
- `Executor`
- `LocalExecutor`

Reviewer notes:

- This is the main boundary file.
- There is intentionally no registry, dependency container, provider router, extension manager, or lifecycle framework.
- `Profile.compact` exists as a no-op-capable hook because compression will become important, but it is not implemented yet.

### `agentd/kernel.py`

Owns the minimal loop. It:

- creates `RunState`
- logs run start
- checks budgets
- calls profile hooks
- writes model request artifacts
- calls provider
- writes response artifact
- dispatches tool calls through policy
- records policy decisions, including allows
- writes final run outputs

Current budget controls:

- `max_turns`
- `max_tool_calls`
- `max_shell_timeout_seconds`
- `max_run_seconds`
- `max_command_output_chars_visible`

Only `max_turns`, `max_tool_calls`, and `max_run_seconds` are enforced in the kernel so far. Shell-specific budgets will matter once shell tools exist.

Reviewer notes:

- Provider exceptions are converted into explicit run failures: `Model provider error: ...`.
- The kernel catches any remaining unexpected exception as `Unhandled exception: ...`.
- The kernel currently writes model artifacts before the provider call. If the provider fails, there is a request/context artifact but no response artifact. This is intentional and useful for debugging failed calls.
- The kernel imports concrete output functions. That is acceptable now, but reviewers should watch that `output.py` does not become a hidden trace manager.

### `agentd/output.py`

Writes durable run outputs:

```text
events.jsonl
summary.md
metrics.json
final.diff
artifacts/context-0001.md
artifacts/model-request-0001.json
artifacts/model-response-0001.json
```

It also emits `ArtifactWritten` events when model context/request/response artifacts are written.

Reviewer notes:

- This file currently combines output flushing and artifact formatting. That is acceptable at current size, but likely the first place to watch for complexity growth.
- Events point to artifact paths instead of embedding large payloads.
- Context markdown is intentionally readable and simple.

### `agentd/models.py`

Implements:

- `ProviderError`
- `FakeModelProvider`
- `OpenAICompatibleConfig`
- `OpenAICompatibleProvider`

The OpenAI-compatible provider uses `urllib.request` rather than adding an SDK dependency. It posts to:

```text
<base_url>/chat/completions
```

Environment variables:

```text
TINYAGENT_MODEL_BASE_URL
TINYAGENT_MODEL_API_KEY
TINYAGENT_MODEL_NAME
TINYAGENT_MODEL_TIMEOUT_SECONDS
```

Reviewer notes:

- No network calls are made in tests.
- Tool call arguments must parse as a JSON object.
- Missing `function.name` is rejected.
- `from_env({})` intentionally does not fall back to real `os.environ`; only `from_env(None)` uses process env.
- This is a minimal OpenAI-compatible implementation, not a full provider abstraction layer.

### `agentctl/cli.py`

Defines a minimal CLI shell:

- `agentctl --version`
- `agentctl run`
- `agentctl replay`

`run` and `replay` are placeholders and intentionally not wired yet.

Reviewer notes:

- CLI implementation should remain thin.
- Real run/replay wiring should happen only after tools/workspace/replay semantics are ready.

## Trace Model

The design requirement is that replay and debugging should be possible from disk artifacts.

Each run writes:

```text
.tinyagent/runs/<run_id>/
  events.jsonl
  summary.md
  metrics.json
  final.diff
  artifacts/
    context-0001.md
    model-request-0001.json
    model-response-0001.json
```

Important invariant:

```text
events point to artifacts; artifacts hold larger payloads.
```

This avoids stuffing full model contexts or command output into `events.jsonl`, while preserving exact context for review.

## Current Tests

Verification command:

```bash
uv run pytest
uv run ruff check .
```

Current result:

```text
15 tests passing
Ruff clean
```

Coverage by intent:

- CLI scaffold and console script declaration.
- Expected top-level scaffold exists.
- Kernel happy path with deterministic tool call.
- Max-turn failure writes required outputs.
- Max-tool-call failure is evented.
- Event taxonomy includes required Milestone 0 events.
- Model context/request/response artifacts are written and referenced from events.
- Event JSONL can be loaded without replaying side effects.
- Fake provider returns deterministic responses and fails when exhausted.
- OpenAI-compatible config reads env-like mappings and validates required fields.
- OpenAI-compatible provider serializes messages/tools and parses tool calls.
- Provider errors surface through kernel as run failures.

## Known Limitations

These are expected at this stage:

- No real tools yet.
- No workspace manager or workspace modes yet.
- No path policy or shell policy yet.
- No real replay CLI yet.
- No synthesized non-git diffs yet.
- No profile implementation beyond placeholder text.
- No extension system.
- No TypeScript SDK.
- No delegated agents.
- No semantic search.
- No container/sandbox execution.

These are not regressions; they are intentionally deferred to later Linear issues.

## Primary Review Questions

Please review with the Tinyagent philosophy in mind:

1. Is the kernel still small enough, or has trace writing made it too aware of artifact mechanics?
2. Should `EVENT_TYPES` remain plain strings, or is an enum worth the added concept?
3. Is `RunState` carrying the right amount of mutable state, or should anything move out?
4. Is `output.py` still a simple writer, or is it already becoming a trace subsystem?
5. Is `models.py` the right level of provider implementation, or should any behavior stay outside core until needed?
6. Are provider errors surfaced with enough context without leaking sensitive request details?
7. Are model request artifacts too raw, or exactly what replay/debugging needs?
8. Are tests asserting the right behavior, or too coupled to event ordering?

## Recommended Next Work

The planned next Linear issue is `BRA-10`: core tool set.

Before adding tools, the implementation should preserve these constraints:

- Tool results should be concise and artifact-backed.
- Shell output must be truncated in model-visible output.
- File tools must resolve symlinks and reject outside-workspace paths.
- Every policy decision must be logged, including allows.
- Shell policy must be documented as best-effort until a real sandbox exists.

The most important thing to avoid next is building a generalized tool registry or middleware layer before the actual tool behavior proves it is needed.

## Source Bundle

For reviewers who want one file with the core Python source, generate:

```bash
python3 scripts/export_py_markdown.py
```

The generated output excludes tests and utility scripts. It includes only core package code from:

```text
agentctl/
agentd/
profiles/
```

The generated output is:

```text
docs/PY_SOURCE_EXPORT.md
```
