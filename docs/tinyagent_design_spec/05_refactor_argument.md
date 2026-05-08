# Refactor Argument and Future Development Path

## The central argument

Tinyagent’s next step should be a minimality-preserving refactor, not a feature expansion. The repo already has enough primitives to support a strong agent harness: events, state, tools, policy, profiles, ContextFS, skills, extensions, index/search, conversations, runtime server, and evals. The problem is that two boundary modules carry too much local responsibility:

- `Kernel` carries orchestration, hooks, policy, approvals, tool execution, workspace delta, ContextFS refresh, observations, index sync, model call tracing, and finalization.
- `ContextFS` carries rendering, indexing, path resolution, artifact kind checks, event sanitization, git status/diff, transcript formatting, observations, and recovery surface rules.

These are not arbitrary messes. They are safety/trace boundaries. The current explicitness is understandable. But the code is now beyond the point where explicitness alone produces clarity.

The correct refactor is narrow extraction with pinned behavior.

## Why not rewrite the Kernel as a graph

A graph runtime would be tempting. It would let you name nodes like `BuildContext`, `CallModel`, `DispatchTool`, `RefreshContextFS`, `FinishGate`, and `Finalize`. But this is the wrong next step.

Reasons:

1. The current loop is still readable.
2. The primary risk is not control flow; it is boundary/event consistency.
3. A graph runtime would add vocabulary before deleting enough code.
4. Product-level multi-agent workflows can use external orchestration later.
5. The tinygrad-like design philosophy favors a compact loop over a framework.

The first Kernel refactor should target duplicated hook execution. That removes code without changing the core loop.

## Why `HookRunner` first

The hook code is repeated and mechanical. It emits similar events, handles similar errors, and performs simple transformations. It is also event-testable.

A `HookRunner` gives immediate benefits:

- shorter `Kernel`;
- one hook error policy implementation;
- one event emission path for hook start/completion/failure;
- simpler addition of future hook methods;
- less risk than refactoring `_dispatch_tool_call` first.

What the `HookRunner` must not do:

- it must not become an extension manager;
- it must not know tool policy;
- it must not know model providers;
- it must not hide events;
- it must not swallow errors unless policy says `record`.

The runner is only a lifecycle-call helper.

## Why ContextFS render plan second

ContextFS is more sensitive than hooks because it defines what the model can recover. A bad ContextFS refactor can degrade agent behavior even if tests pass superficially.

Still, the rendering part is clearly separable. Today, `_index_text`, `_task_text`, `_repo_state_text`, `_observations_text`, `_transcript_text`, `_write_tool_docs`, `_write_diff_docs`, and `refresh_contextfs` all mix file identity, content rendering, path presentation, and safety filtering.

A render plan solves this without inventing a virtual filesystem:

```python
@dataclass(frozen=True)
class ContextFileSpec:
    rel: str
    section: str
    title: str
    description: str
    render: Callable[[RunState], str]
    include_in_index: bool = True
    static_allowed: bool = True
```

`refresh_contextfs` becomes:

1. build specs;
2. render each file;
3. write generated tool docs and diff docs;
4. render index from specs and dynamic entries;
5. emit one index update event.

Path policy, artifact exposure, and sanitization remain explicit functions.

This is not “abstraction for abstraction’s sake.” It separates a data list from safety code and lets tests assert exact files.

## Why add `tiny-pi` instead of shrinking `tiny-coder`

The current profile is useful. It has finish gates, dynamic context sources, skills, context planning, verification discipline, and a broader tool surface. Shrinking it directly would lose a useful robust profile.

A separate `tiny-pi` profile lets tinyagent evaluate the philosophy honestly:

- Does a four-tool profile solve more cleanly?
- Does it reduce context token load?
- Does it reduce model confusion?
- Does it increase unsafe or repeated shell behavior?
- Does it hurt verification discipline?

This is a scientific design choice. Keep both profiles and compare them.

## Why SDK before product UI

A real SDK clarifies the runtime contract. Product UI can then consume the same contract as tests, scripts, and external tools. If UI comes first, the protocol tends to grow around UI details.

The SDK should expose:

- run handles;
- async event iteration;
- cancellation;
- approval callbacks;
- final result retrieval;
- public artifact access;
- replay/fork helpers.

This makes tinyagent useful as a kernel while keeping product shells optional.

## Why route unification matters

The repo currently has duplicated handler logic across runtime and product HTTP layers. Duplication creates safety drift. The artifact exposure issue is exactly the kind of drift that duplication causes.

A single run-route implementation with an injected resolver keeps product mode and single-workspace mode consistent.

Target:

```python
class RunResolver(Protocol):
    def controller_for_run(self, run_id: str, query: str) -> RunController: ...
    def workspace_id_for_controller(self, controller: RunController) -> str: ...
```

Then route code does not know whether it is product-wide or single-workspace.

## Why memory comes later

Hermes shows that self-improvement and memory can be powerful. But memory is also where agent systems become opaque. Tinyagent should not put persistent memory into the core loop.

The first memory/self-improvement path should be:

1. Mine successful traces.
2. Generate a skill draft in a file.
3. Run evals against the draft.
4. Require human review.
5. Install as a skill resource if accepted.
6. Keep rollback metadata.

This matches tinyagent’s file-backed, reviewable philosophy.

## Refactor dependency graph

```text
Stage 0 safety fixes
  -> Stage 1 HookRunner
      -> Stage 1b tool dispatch cleanup
  -> Stage 2 ContextFS render plan
      -> Stage 3 tiny-pi profile
          -> Stage 5 pi-vs-coder evals
  -> Stage 4 route unification
      -> Stage 4 SDK run handles
          -> product shells and automation
  -> Stage 5 event invariants
      -> all future work
  -> Stage 6 skill learning
      -> requires stable skills/evals/artifacts
```

## What must stay stable

These contracts should be treated as public or semi-public:

- durable event JSON shape;
- run output files: `events.jsonl`, `metrics.json`, `final.md`, `final.diff`;
- public artifact visibility rules;
- ContextFS refs that the model sees;
- policy decision fields;
- approval request/resolution fields;
- tool result fields used by observations/evals;
- run summary and v1 API response basics.

Any change to these should be versioned or snapshot-tested.

## Recommended final architecture after this roadmap

At the end of the proposed roadmap, tinyagent should look like this:

```text
tinyagent.core
  kernel.py              # small orchestrator loop
  hook_runner.py         # lifecycle hook execution and trace events
  tool_dispatch.py       # optional extracted guarded dispatch pipeline
  contextfs.py           # safety/path/public API surface
  contextfs_render.py    # pure file specs and renderers
  profiles.py            # tiny-coder and tiny-pi profiles
  resources.py           # ResourceLoader for extensions/skills/templates/context files
  sdk.py                 # cancellable run handles and typed results
  events.py              # event contract
  state.py               # run state and core dataclasses

tinyagent.runtime
  routes.py              # shared run routes
  resolver.py            # single/product run resolver protocols
  server.py              # single-workspace server shell

tinyagent.app
  server.py              # product resolver + app-specific endpoints

tinyagent.evals
  invariants.py          # event/artifact invariants
  profiles.py            # profile comparison runners
```

The exact filenames can change. The important point is responsibility separation.

## Final recommendation

Do not optimize for “less code” alone. Optimize for fewer live concepts in the default path.

The default path should be:

1. Load a profile.
2. Prepare workspace.
3. Emit run start.
4. Build minimal context.
5. Call model.
6. Dispatch tool through guards.
7. Write events/artifacts/ContextFS.
8. Repeat until finish.
9. Finalize outputs.

Everything else should be optional.
