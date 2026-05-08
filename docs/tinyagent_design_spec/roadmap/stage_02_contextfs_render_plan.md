# Stage 2 — ContextFS Render Plan

## Goal

Reduce ContextFS bulk by separating rendering from safety/path policy. Keep ContextFS file-first and explicit.

## Why this is necessary

ContextFS is one of tinyagent’s strongest ideas, but `contextfs.py` currently does too much. The rendering logic is large and repetitive; safety logic is mixed with presentation logic; index generation is manual; generated file identity is not data-driven.

The refactor should preserve the ContextFS philosophy:

- files, not hidden memory;
- bounded recovery surface;
- dynamic reads, not giant prompts;
- explicit allowlist;
- safe artifact refs.

It should not introduce a virtual filesystem framework.

## Substages

1. `stage_02a_context_file_specs.md`
2. `stage_02b_stable_refs_no_absolute_paths.md`
3. `stage_02c_contextfs_search_read_edges.md`

## Primary changes

- Add `ContextFileSpec` and `ContextIndexEntry` data types.
- Move pure renderers into `contextfs_render.py` or similar.
- Make `refresh_contextfs()` iterate specs and dynamic entries.
- Keep `resolve_context_path`, `allowed_context_read_paths`, artifact kind checks, and sanitization explicit.
- Add snapshot tests for generated ContextFS files.

## Proposed files

```text
tinyagent/core/contextfs.py          # safety/path/read public API
tinyagent/core/contextfs_render.py   # pure render specs and renderers
tinyagent/core/contextfs_index.py    # optional, if index rendering needs separation
```

Avoid too many files initially. `contextfs_render.py` plus existing `contextfs.py` may be enough.

## Exit criteria

- `refresh_contextfs()` is shorter and spec-driven.
- Generated ContextFS files are byte-equivalent or intentionally changed with tests.
- Allowed read paths still match generated files.
- Hidden path and artifact safety tests pass.
- ContextFS index is stable and uses relative refs.

## Risks

### Risk: weakening recovery

ContextFS is model-facing. Run evals and snapshot generated files before/after.

### Risk: over-abstracting

The render plan should be a list of file specs, not a class hierarchy.

### Risk: breaking old refs

Keep existing `context/...` paths stable unless a change is explicitly documented.
