# TinyAgent TUI Contract

The TUI is a client of the existing Python runtime. It must not own agent execution, tool policy, approval state, run storage, or event persistence.

## Backend Boundary

The Python backend keeps these responsibilities:

- `Kernel` owns the run loop, model calls, tool dispatch, policy checks, and finalization.
- `RunController` owns background run threads, cancellation, run lookup, and event streaming.
- `RunBus` carries live events.
- `SurfaceEventLogSink` persists the public surface event stream beside the durable run log.
- `ApprovalBroker` owns pending approval requests and resolution.
- `RunStore` and `ConversationStore` own recorded runs and conversation turns.
- `/v1` is the public TUI protocol.

The TUI may call `/v1`; it may not import Python modules, parse private run files directly, or depend on hidden process globals.

## Public Protocol

The TUI uses:

- `GET /v1/health`
- `GET /v1/workspaces`
- `GET /v1/workspaces/{workspace_id}/files`
- `GET /v1/workspaces/{workspace_id}/git/status`
- `GET /v1/conversations?workspace_id=...`
- `GET /v1/conversations/{conversation_id}/turns?workspace_id=...`
- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/events`
- `GET /v1/runs/{run_id}/events.jsonl`
- `GET /v1/runs/{run_id}/artifacts`
- `GET /v1/runs/{run_id}/approvals`
- `POST /v1/runs/{run_id}/approvals/{approval_id}/resolve`
- `POST /v1/runs/{run_id}/cancel`
- `POST /v1/runs/{run_id}/fork`

The schema export command is:

```bash
uv run python scripts/export_surface_schema.py > tui/src/protocol/schema.generated.json
```

## Event Projection

All TUI state is derived from `RunEvent` objects through a pure reducer:

```ts
reduceEvent(state, event)
```

Components render selectors and projected state. Components must not interpret raw event payloads directly when reducer state exists.

## Plan Mode

`session_mode=plan` is a backend mode. It blocks workspace mutation tools and shell commands that look like writes before `approval_mode=yolo` can bypass policy. Read/search/inspection commands continue through normal policy evaluation.
