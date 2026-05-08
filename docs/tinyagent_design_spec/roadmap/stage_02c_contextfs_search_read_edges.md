# Stage 2c — ContextFS Search and Read Edge Handling

## Problem

ContextFS search currently reads allowed files to score them. If a file is too large, `_read_bounded_text()` can raise and abort the search. That is too brittle for a recovery surface.

## Target behavior

- `context_search` should be best-effort and robust.
- One oversized file should not fail the entire search.
- `context_read` should still enforce size and path limits.
- Search results should clearly indicate when content was skipped.

## Implementation options

### Option A: skip oversized files

Simple and safe:

```python
try:
    text = _read_bounded_text(path)
except ValueError:
    return None
```

Pros: minimal.
Cons: path-only matches on large files impossible.

### Option B: path-only stub

If query terms match the path, return a stub:

```python
ContextRef(
    ref="contextfs:context/history/raw.jsonl",
    title="context/history/raw.jsonl",
    kind="file_large",
    summary="File is too large for search; use bounded context_read or inspect artifacts.",
    score=0.5,
)
```

Pros: user/model sees existence.
Cons: may encourage reads that fail if full file too large.

Recommendation: implement Option B for path matches, skip otherwise.

## Read behavior

`context_read` currently reads full text then slices lines. For large files, this can fail. A future improvement is line-bounded streaming reads. For this stage:

- keep full-size refusal if simpler;
- return a clear error message;
- add read hints for safe alternatives if available.

Later, implement bounded streaming line reads for large ContextFS files if needed.

## Tests

### Oversized non-matching file

- Create large allowed ContextFS file.
- Search unrelated query.
- Assert search succeeds and omits file.

### Oversized path-matching file

- Search query matching the filename.
- Assert search succeeds and returns stub with kind `file_large` or similar.

### Oversized read

- `context_read` oversized file.
- Assert clear failure kind and no crash.

### Mixed search

- One oversized file and one normal matching file.
- Assert normal file is returned.

## Exit criteria

- `context_search` never fails due only to a large allowed file.
- Oversized behavior is documented in tool output.
- Tests cover mixed search.

## Why this matters

ContextFS is the recovery interface. Recovery tools should degrade gracefully. A recovery surface that breaks on large recovery files is self-defeating.
