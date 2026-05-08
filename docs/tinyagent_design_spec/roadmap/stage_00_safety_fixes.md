# Stage 0 — Safety and Correctness Boundary Fixes

## Goal

Fix known boundary issues before refactoring. This stage is deliberately small but high priority. It protects the trust contract of the harness.

## Why this is necessary

Tinyagent’s strongest asset is traceability. Traceability loses value if internal artifacts can be fetched through legacy routes, approval waits can leave stale state, or ContextFS discovery can fail on edge cases. These are not aesthetic issues. They are correctness and safety issues.

Stage 0 also creates the test scaffolding needed for later refactors. If event and artifact boundaries are pinned, later simplification can proceed without guessing.

## Substages

1. `stage_00a_public_artifact_boundary.md`
2. `stage_00b_approval_step_closure.md`
3. `stage_00c_contextfs_safety_edges.md`

## Primary changes

- Ensure every artifact-fetch route uses `RunController.public_artifact_path()` or equivalent.
- Return `403` for hidden artifacts, not `200` or silent direct reads.
- Add tests for both legacy `/api` and `/v1` artifact routes.
- Ensure approval wait steps close if the approval handler raises.
- Avoid absolute product-home paths in model-visible ContextFS refs.
- Ensure `context_search` skips or summarizes oversized files instead of failing whole searches.

## Files likely touched

- `tinyagent/runtime/server.py`
- `tinyagent/app/server.py`
- `tinyagent/core/kernel.py`
- `tinyagent/core/contextfs.py`
- `tinyagent/core/context_sources/builtin.py`
- `tests/runtime/*`
- `tests/core/*`

## Event invariants introduced

- Hidden artifacts never appear in public listing.
- Hidden artifacts cannot be fetched through any public route.
- Approval wait steps always close with completed, failed, or cancelled status.
- ContextFS refs shown to the model are stable relative refs, not host absolute paths, except where explicitly configured for debug.

## Exit criteria

- All new safety tests pass.
- Legacy and v1 artifact routes behave consistently.
- No public route can fetch model request artifacts, model response artifacts, context report artifacts, or ContextFS internals by direct path.
- Approval handler exception path does not leave `state.current_step_kind == "approval_wait"`.
- ContextFS search does not fail the entire query because one generated file is too large.

## Risks

### Risk: breaking existing UI/API clients

Some clients may rely on legacy artifact direct access. That is exactly the behavior that should be removed. If internal artifact access is needed, add an authenticated/debug route later; do not keep it public.

### Risk: losing useful debug information

Debug information remains in run output directories and can be accessed locally. Public HTTP artifact exposure should be safe by default.

## Implementation advice

Do this stage in separate PRs. The artifact boundary fix should be independent of approval and ContextFS fixes.
