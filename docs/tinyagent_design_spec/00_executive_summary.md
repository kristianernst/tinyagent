# Executive Summary

## Final direction

Tinyagent should move toward a Pi-like philosophy while keeping the trace, safety, and eval discipline that already make the repo valuable. The next version should feel like this:

> A minimal agent kernel whose primitives are obvious, whose traces are complete, whose state is file-readable, and whose power comes from profiles, skills, and extensions rather than a bloated default loop.

The current repo is not messy in the usual framework sense. It is overly explicit in the two places where explicitness was a reasonable defensive choice: `Kernel` and `ContextFS`. The refactor should therefore not collapse the code into a clever framework. It should extract narrow seams while preserving event output and safety behavior.

## Strategic thesis

The best modern coding-agent harnesses are converging on five ideas:

1. Dynamic context beats static prompt bloat.
2. Files are a robust interface between model, tools, history, and recovery state.
3. Sandboxes and approvals should reduce interruption without making unsafe execution invisible.
4. Tool and prompt surfaces should be tuned per model and per workflow.
5. Evals must include the harness, not only the model.

Pi takes the most radical minimal route: very few built-in tools, a tiny default prompt, user-controlled extensions, no built-in plan mode, no built-in todos, no subagents, no MCP by default, and a “primitives, not features” philosophy. Cursor, Codex, Claude Code, OpenCode, and Hermes show what must still be supported around that core: dynamic context, safety envelopes, protocols, rich product surfaces, skills, memory, and continuous improvement. The tinyagent design target should be Pi-shaped at the kernel/profile layer and Cursor/Codex-shaped at the trace/eval/safety boundary.

## Immediate refactor order

### 0. Safety and correctness first

Before elegance work, fix known boundary issues. The most important likely issue is that the legacy artifact route appears to serve hidden artifacts if a caller knows the path. The v1 artifact path uses the safer public artifact path, but the base route calls `store.artifact_path()` directly. This should be fixed before broader ContextFS work.

Also fix approval-step closure on handler exceptions and ContextFS path/search edge cases. These are small, testable changes with high confidence.

### 1. Extract a hook runner

`Kernel` currently repeats hook tracing logic across multiple methods. This is the lowest-risk `Kernel` deslop target because it is narrow and behavior-preserving. A `HookRunner` should emit the exact same `hook.started`, `hook.completed`, and `hook.failed` events and should be tested with event snapshots.

Do not split the whole Kernel yet. Keep the single readable loop.

### 2. Convert ContextFS rendering into a render plan

ContextFS should not become a virtual filesystem abstraction. It should remain a simple file surface. The specific refactor is to separate “which files exist and how they are rendered” from path policy, artifact-kind checks, and sanitization. The target is a list of `ContextFileSpec`s and `ContextIndexEntry`s that `refresh_contextfs()` writes.

The result should reduce bulk without weakening the recovery surface.

### 3. Add `tiny-pi` profile and resource loading

The current `ApexCoderProfile` is closer to a full coding harness. Add a separate lean profile:

- default tools: `read_file`, `write_file` or model-specific edit, `apply_patch`/`str_replace_edit`, `shell`;
- optional tools: `grep`, `find`, `ls` style helpers or aliases;
- no default MCP/LSP/todo context;
- no default planning/todo artifact;
- ContextFS available as file/read hints, not as a heavy prompt concept;
- small prompt and strict file-backed state.

Then add a `ResourceLoader` concept inspired by Pi: discover extensions, skills, prompt templates, themes or UI metadata, and context files without hardwiring all of them into `Kernel`.

### 4. Make the SDK real

`core/sdk.py` should provide cancellable run handles, async event iteration, result retrieval, approval callbacks, and typed artifact access. It should not require users to reconstruct state from raw events.

### 5. Make evals enforce the philosophy

Add eval gates that compare `tiny-pi` against `tiny-coder`, verify event invariants, protect safety boundaries, measure context bloat, and catch regressions in edit/test/diff behavior.

### 6. Add memory and self-improvement later

Hermes-style learning is useful, but it is too easy to bloat the core. Memory should remain file-backed and optional. Skill creation should be review-gated: mine traces, propose a skill draft, run an eval, require approval, then install.

## Non-goals

Do not build these now:

- a general graph engine inside tinyagent;
- a default multi-agent orchestrator;
- mandatory MCP/LSP/todo memory in the default profile;
- a native sandbox abstraction before fixing artifact/protocol boundaries;
- a database-backed state layer in the kernel;
- a full product UI before SDK/protocol unification;
- an opaque self-improving memory loop.

## Target identity

Tinyagent should be small enough that its core can be explained as:

- `ModelProvider` proposes text and tool calls.
- `Profile` decides prompt, tools, compaction, finish gates.
- `Policy` decides whether tool calls may run.
- `Executor` runs tools.
- `RunState.emit()` records the trace.
- `ContextFS` writes file-backed recovery state.
- `Extensions` add tools, hooks, context sources, and skills.

Everything else is a shell around these primitives.
