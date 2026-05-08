# Design Decision Log

## Decision 1: Keep the kernel loop, do not introduce a graph runtime

Status: accepted.

Reason: the current loop is still comprehensible. The real complexity is boundary repetition and ContextFS rendering bulk, not the absence of graph orchestration. A graph runtime would add vocabulary and indirection before deleting enough code.

Implication: future multi-agent or workflow logic should start outside the kernel, using SDK run handles, event streams, and shared files.

## Decision 2: Extract `HookRunner` before `ToolDispatcher`

Status: accepted.

Reason: hook execution is duplicated, mechanical, and event-testable. Tool dispatch is more semantically dense and should not be extracted until invariants are stronger.

Implication: Stage 1a is the first elegance refactor after Stage 0 safety fixes.

## Decision 3: Refactor ContextFS through render specs, not a virtual filesystem

Status: accepted.

Reason: ContextFS’s value is that it is simple, file-backed, and readable. A virtual filesystem abstraction would conflict with that design. Render specs remove duplication while keeping files and safety explicit.

Implication: `contextfs.py` remains the safety/path surface; `contextfs_render.py` handles pure rendering.

## Decision 4: Add `tiny-pi` as a separate profile

Status: accepted.

Reason: the current robust profile is useful. Shrinking it directly would lose capability and prevent clean comparison. A separate `tiny-pi` profile makes the design philosophy measurable.

Implication: evals compare `tiny-pi` and `tiny-coder`; default product config can choose either.

## Decision 5: Keep MCP, LSP, todo memory, semantic search, and self-improvement optional

Status: accepted.

Reason: these are useful but violate the lean default if prompt/tool-injected automatically. They belong in extensions, profiles, or product shells.

Implication: ResourceLoader and profile tool surfaces decide whether these appear.

## Decision 6: Fix artifact visibility before refactoring

Status: accepted.

Reason: hidden artifact exposure through legacy routes is a trust issue. It must be fixed before ContextFS or protocol refactors.

Implication: Stage 0a is the first implementation substage.

## Decision 7: Make SDK runs long-running actions

Status: accepted.

Reason: agent runs need events, cancellation, approvals, and final results. A raw async generator is insufficient.

Implication: add `RunHandle`, `RunResult`, cancellation token wiring, and approval callback support.

## Decision 8: Memory is files and skills first

Status: accepted.

Reason: hidden persistent memory is opaque. Skills and markdown memory files are reviewable, diffable, and removable.

Implication: Hermes-inspired learning enters as skill drafts, not automatic self-modification.

## Decision 9: Product surfaces consume SDK/protocol, not Kernel internals

Status: accepted.

Reason: CLI/TUI/IDE/cloud features are valuable, but putting product concerns into Kernel will erode minimality.

Implication: route unification and SDK stabilization come before product surface expansion.
