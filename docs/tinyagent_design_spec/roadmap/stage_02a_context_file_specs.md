# Stage 2a — Context File Specs

## Problem

ContextFS file rendering is currently encoded as a sequence of manual `_write_text()` calls and helper functions. The index is manually assembled and must stay in sync with generated files.

## Target design

Add data specs:

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

Optional:

```python
@dataclass(frozen=True)
class ContextIndexEntry:
    path: str
    section: str
    description: str
    read_hint: str = ""
```

## Static specs

Start with specs for:

- `context/task.md`;
- `context/environment.md`;
- `context/current_status.md`;
- `context/current_diff.patch`;
- `context/current_diff.md`;
- `context/last_failure.md`;
- `context/observations.md`;
- `context/transcript.md`;
- `context/history/compacted.md`;
- `context/history/summary.md`;
- `context/history/raw.jsonl`;
- `context/tools/INDEX.md`;
- `context/diffs/INDEX.md`;
- `context/memory/todo.md` if present.

## Implementation plan

1. Create `contextfs_render.py`.
2. Move pure render helpers into it.
3. Define `static_context_file_specs(state)`.
4. Update `refresh_contextfs(state)` to:
   - create context dir;
   - iterate specs;
   - write rendered contents;
   - write dynamic tool docs/diff docs;
   - collect index entries;
   - render `INDEX.md` from entries.
5. Keep old helper names temporarily if tests depend on them.
6. Remove duplication after snapshots pass.

## Snapshot tests

Create a synthetic `RunState` with:

- no tools;
- one successful shell output;
- one failing shell output;
- one edit with workspace delta;
- one observation;
- one compaction checkpoint.

For each state, snapshot:

- generated file list;
- `context/INDEX.md`;
- `context/task.md`;
- `context/last_failure.md`;
- `context/observations.md`;
- `context/transcript.md`;
- `context/tools/INDEX.md`;
- `context/diffs/INDEX.md`.

Snapshot stable fields only where timestamps/IDs differ.

## Exit criteria

- Static files are generated from specs.
- Index entries come from specs/dynamic entries.
- Existing allowed read paths include all generated specs.
- ContextFS file snapshots pass.

## Why this is necessary

A render spec gives you lean code without hiding safety. It also makes future additions cheaper: adding a file becomes adding a spec, not editing several functions and indexes.
