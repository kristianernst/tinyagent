# Stage 0a — Public Artifact Boundary

## Problem

The runtime has two concepts:

- artifact storage path: any file under a run output directory;
- public artifact path: only files safe to expose through HTTP/API.

`RunController.artifacts()` hides internal artifacts from listing, and `public_artifact_path()` rejects hidden artifacts. However, the legacy artifact route in `RuntimeHandler._artifact()` calls `controller.store.artifact_path()` directly. That bypasses the public-artifact policy if a caller knows the internal path.

## Target behavior

All artifact-serving routes must enforce the same rule:

| Path kind | Listing | Fetch |
| --- | ---: | ---: |
| `final.md` | Yes | 200 |
| `final.diff` if exposed | Yes or controlled | 200 or 404 by policy |
| public summary artifacts | Yes | 200 |
| `artifacts/model-request-*` | No | 403 |
| `artifacts/model-response-*` | No | 403 by default |
| `artifacts/context-*` | No | 403 |
| `artifacts/context-report-*` | No | 403 |
| `context/*` | No through artifact API | 403 |
| path traversal | No | 400 or 403 |

## Code changes

### RuntimeHandler

Change:

```python
path = controller.store.artifact_path(run_id, unquote(relative_path))
```

to:

```python
try:
    path = controller.public_artifact_path(run_id, unquote(relative_path))
except PermissionError as exc:
    self._json(HTTPStatus.FORBIDDEN, {"error": str(exc)})
    return
```

Use the same pattern already present in the v1 product artifact handler.

### ProductRuntimeHandler

Audit all artifact paths. The v1 route currently calls `_v1_artifact`, which uses `public_artifact_path()`. The legacy `/api` route inherits/uses `_artifact`; after fixing the base implementation, product mode should become safe too.

### Artifact hiding policy

Centralize hidden checks in one function. Current `_artifact_hidden_by_default()` is in `runtime/server.py`; keep it there or move to a small `runtime/artifacts.py` if needed.

Do not duplicate hidden-path regexes in product code.

## Tests

Create a runtime HTTP test that starts a fake run or writes a synthetic run directory with events/artifacts.

Required tests:

```text
GET /api/runs/<id>/artifacts/final.md                         -> 200
GET /api/runs/<id>/artifacts/artifacts/model-request-0001.json -> 403
GET /api/runs/<id>/artifacts/artifacts/model-response-0001.json -> 403
GET /api/runs/<id>/artifacts/artifacts/context-0001.md         -> 403
GET /api/runs/<id>/artifacts/context/INDEX.md                  -> 403
GET /api/runs/<id>/artifacts/../events.jsonl                   -> 400/403
GET /v1/runs/<id>/artifacts/final.md                           -> 200
GET /v1/runs/<id>/artifacts/artifacts/model-request-0001.json  -> 403
```

Also test listing:

```text
GET /v1/runs/<id>/artifacts -> does not include hidden artifacts
GET /api/runs/<id>/artifacts listing if supported -> does not include hidden artifacts
```

## Event implications

No event output should change. This is an API serving fix, not a run trace change.

## Exit criteria

- Hidden artifact fetches return `403` on all public routes.
- Public artifacts still fetch.
- Path traversal remains blocked.
- No duplicated artifact policy logic is added.

## Why this is first

A lean harness must be trustworthy. Leanness without safe artifact boundaries becomes “simple because it leaks.” Fixing this makes later ContextFS work safer.
