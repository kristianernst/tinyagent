# Stage 2b — Stable Refs and No Absolute Paths

## Problem

Model-visible ContextFS paths can become absolute host paths when run outputs live outside the workspace. This can happen in product home mode. Absolute paths are noisy, leak local filesystem structure, and are less stable across machines.

## Target behavior

ContextFS index and model-visible hints should use stable run-relative refs:

- `context/task.md`;
- `context/current_diff.patch`;
- `context/tools/shell.md`;
- `artifacts/workspace-delta-0001.patch` when safe;
- `contextfs:context/task.md` in context-source references.

Only local debug artifacts should include absolute filesystem paths.

## API proposal

Introduce:

```python
def context_ref(relative: str | Path) -> str:
    rel = Path(relative).as_posix()
    return rel if rel.startswith(("context/", "artifacts/")) else f"context/{rel}"


def context_read_ref(relative: str | Path) -> str:
    return f"contextfs:{context_ref(relative)}"
```

Review `model_readable_path()`. Either:

- keep it only for user-visible filesystem paths, with renamed semantics; or
- replace usage in ContextFS index with `context_ref()`.

## Code changes

Update these functions:

- `_index_text`;
- `_last_failure_text`;
- `_write_tool_docs`;
- `_write_diff_docs`;
- `read_hints` usage where hints should be model refs rather than shell filesystem paths;
- `ContextFsSource` result titles/paths.

Be careful: shell read hints like `tail -120 <path>` may need actual filesystem paths if they are intended for shell. For model-facing context tools, prefer `context_read({"ref":"contextfs:..."})` hints.

## Tests

### Product-home output test

Construct state:

- workspace root: `/tmp/workspace/project`;
- output dir: `/tmp/product-home/workspaces/ws/runs/run_1`.

Run `refresh_contextfs()`.

Assert:

- `context/INDEX.md` does not contain `/tmp/product-home`;
- `context/INDEX.md` contains `context/task.md`;
- generated tool docs contain stable refs;
- failure artifact refs are stable/safe.

### Workspace-output test

When output is inside workspace, stable refs should still be used. Do not rely on incidental relative paths.

## Exit criteria

- No product home absolute paths in ContextFS index or model-facing generated files.
- Context refs are stable across output locations.
- Shell-specific hints remain functional or are clearly replaced with context-read hints.

## Why this matters

A minimal harness should not leak implementation details into the model’s working memory. Stable refs make traces portable, testable, and less distracting.
