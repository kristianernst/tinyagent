# Stage 4c — Route Unification and v1 Schema

## Problem

`RuntimeHandler` and `ProductRuntimeHandler` duplicate many routes. Duplication caused or contributed to artifact visibility drift. The v1 protocol is useful but hand-written and only partially schema-backed.

## Target design

Create shared route handling with resolver injection.

```python
class RunResolver(Protocol):
    def controller_for_run(self, run_id: str, *, workspace_id: str | None = None) -> RunController: ...
    def controller_for_workspace(self, workspace_id: str) -> RunController: ...
    def workspace_id_for_controller(self, controller: RunController) -> str: ...
```

Shared route layer handles run routes. Product handler adds workspace registration and product-specific endpoints.

## Route consolidation

Shared routes:

- `GET /v1/runs`
- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/events`
- `GET /v1/runs/{run_id}/events.jsonl`
- `GET /v1/runs/{run_id}/artifacts`
- `GET /v1/runs/{run_id}/artifacts/{path}`
- `GET /v1/runs/{run_id}/approvals`
- `POST /v1/runs/{run_id}/cancel`
- `POST /v1/runs/{run_id}/approvals/{approval_id}/resolve`

Legacy `/api` routes can delegate to shared helpers or be deprecated.

## Schema discipline

Add explicit schemas for:

- event object;
- run object;
- artifact object;
- approval request/resolution;
- error response;
- workspace object.

The existing `openapi_spec()` can be expanded gradually. It does not need full generation yet, but should stop being a placeholder.

## Tests

- Single-workspace server route tests.
- Product server route tests with workspace_id.
- Artifact route safety tests in both modes.
- Error response shape tests.
- SSE event shape tests.
- `after_seq` and `Last-Event-ID` behavior tests.

## Exit criteria

- Artifact/event/run route logic is not duplicated across handlers.
- v1 response shapes are documented and tested.
- Legacy routes either delegate or are explicitly marked compatibility-only.

## Why this matters

Protocol drift is an enemy of a traceable harness. A lean kernel can still have a disciplined protocol, and route unification prevents safety bugs.
