# Stage 0c — ContextFS Safety Edges

## Problem

ContextFS is model-readable recovery state. Small edge cases can leak host paths, fail searches, or confuse the model.

Known edge concerns:

1. `model_readable_path()` can return absolute paths when the run output directory is outside the workspace, which happens in product-home mode.
2. `ContextFsSource.search()` can fail the whole search if one allowed file is larger than `MAX_CONTEXT_SOURCE_READ_BYTES`.
3. Context refs should be stable and relative wherever possible.

## Target behavior

- Model-visible ContextFS refs should prefer stable refs like `context/task.md` or `contextfs:context/task.md`.
- Host absolute paths should appear only in explicit debug/internal artifacts, not normal model-visible indexes.
- Context search should skip oversized files or return bounded stubs without aborting the whole search.
- Context read should still enforce size/path safety.

## Code changes

### Stable display refs

Introduce a function such as:

```python
def context_display_ref(state: RunState, relative: str | Path) -> str:
    rel = Path(relative).as_posix()
    if rel.startswith(("context/", "artifacts/")):
        return rel
    return f"context/{rel}"
```

Use it in `_index_text`, `_write_tool_docs`, `_write_diff_docs`, and failure artifact references. Keep `model_readable_path()` for cases where an actual filesystem path is required, or rename it to clarify behavior.

### Oversize search handling

In `ContextFsSource.search()` / `_file_match_ref()`:

- catch `ValueError` from `_read_bounded_text()`;
- optionally score path-only matches;
- include summary like `file too large for search; use context_read with line bounds` only if useful;
- never abort the entire search because one file is large.

### Sanitization tests

Add tests around:

- `.env`, `.env.local`, `.npmrc`, `.ssh` hidden paths;
- product home path redaction;
- output directory path replacement;
- model request artifacts redacted from raw history.

## Tests

### Product-home path test

Create a workspace and output dir outside workspace.

Expected ContextFS index:

- contains `context/task.md`, `context/current_status.md`, etc.;
- does not contain `/home/.../.tinyagent/...` absolute product-home paths;
- does not contain full run output absolute path.

### Oversize search test

Create a large allowed context file and call `context_search`.

Expected:

- search completes;
- no unhandled exception;
- other refs still returned;
- oversized file either skipped or represented safely.

### Hidden-path tests

Create repo status/diff entries involving `.env.local`, `.ssh/config`, `.tinyagent`, and output dirs.

Expected:

- hidden paths do not appear in index/status/diff text;
- sanitized placeholders appear where needed.

## Exit criteria

- ContextFS model-visible indexes are stable-relative in product-home mode.
- Oversized ContextFS files do not break search.
- Sanitization tests pass.

## Why this is Stage 0

This is not a major ContextFS refactor. It is boundary cleanup needed before changing the renderer architecture.
