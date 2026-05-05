# Surface Event Contract

Tinyagent surfaces consume runtime events. They should not parse terminal output,
model-provider chunks, or UI-specific projections.

## Default Runtime Stream

The default HTTP event stream is `GET /api/runs/{run_id}/events`.

Each SSE message uses:

```text
id: <event.seq>
event: <event.type>
data: <event JSON envelope>
```

`seq` is monotonic per run. Clients can resume with `after_seq=N` or
`Last-Event-ID: N`.

The runtime never sends `visibility=internal` events on the default stream.
Public surfaces should also ignore unknown event types and any event they do not
intend to render.

## Minimum Surface Events

The default stream is expected to carry these event types when they occur:

```text
run.started
turn.started
model.call.started
model.text.delta
model.message.completed
model.tool_call.assembly.completed
tool.execution.started
tool.execution.completed
tool.execution.failed
tool.execution.blocked
tool.execution.cancelled
approval.requested
approval.resolved
artifact.materialized
workspace.mutation.detected
run.completed
run.failed
run.cancelled
```

## Correlation Rules

Tool UI state is correlated by `event.data.tool_call_id`, not by `event.item_id`.

Artifact paths in `artifact_refs`, `data.path`, `data.output_path`,
`data.artifact_path`, and related fields are fetched through:

```text
GET /api/runs/{run_id}/artifacts/{path}
```

`model.text.delta` is live-only. After a run completes, clients must recover the
durable assistant answer from `model.message.completed.data.output_path`, usually
`final.md`.

Large payloads stay in artifacts. Events should remain small metadata.

`artifact.created` is a debug event by default because it can expose internal
request, response, and context artifact paths. Public surfaces should rely on
`artifact.materialized` and explicit user-visible artifact refs unless they
request a higher debug level.
