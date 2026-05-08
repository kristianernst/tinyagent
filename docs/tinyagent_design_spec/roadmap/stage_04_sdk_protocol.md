# Stage 4 — SDK and Protocol

## Goal

Make tinyagent usable as a stable programmable harness, not only a CLI/server. Fix cancellation, expose approvals, and unify route behavior.

## Why this is necessary

A lean kernel becomes much more valuable when it has a clean SDK and protocol. Pi provides SDK/RPC modes. Codex has an app-server. Claude and OpenAI SDKs expose run results, tools, permissions, and human review. Tinyagent’s current SDK is a thin async generator and the runtime/product route code is duplicated.

Stage 4 turns the runtime contract into a first-class artifact.

## Substages

1. `stage_04a_cancellable_sdk_run_handle.md`
2. `stage_04b_approval_callback_api.md`
3. `stage_04c_route_unification_v1_schema.md`

## Primary changes

- Add `RunHandle` and `RunResult` to SDK.
- Wire `CancelToken` through async SDK runs.
- Provide approval callback or approval queue.
- Unify runtime/product artifact/event routes with resolver injection.
- Add schema/version discipline for v1 protocol.

## SDK target API

```python
agent = Agent.create(
    workspace=".",
    provider=provider,
    profile="tiny-pi",
    tools=default_tools(),
    policy=default_policy(),
)

run = await agent.start("fix the parser")

async for event in run.events():
    ...

await run.cancel("user_cancelled")
result = await run.result()
```

One-shot helper:

```python
result = await agent.run_once("fix the parser")
```

## Runtime route target

One implementation should handle:

- get/list runs;
- stream events;
- get events JSON;
- list/fetch public artifacts;
- cancel;
- approval resolve;
- fork;
- conversation turn where configured.

Product server injects a workspace-aware resolver. Single-workspace runtime injects a trivial resolver.

## Exit criteria

- SDK cancellation stops the underlying thread/run.
- SDK can handle approvals without HTTP server.
- Legacy and v1 artifact routes enforce the same public-artifact policy.
- Protocol schema or documented response contracts exist.
- Route duplication is reduced.

## Risks

### Risk: SDK grows into product API

Keep SDK focused on runs, events, approvals, results, and artifacts. Product UX remains separate.

### Risk: route unification breaks product mode

Write route tests for both single-workspace and product resolvers.

### Risk: cancellation remains best-effort

Local tool execution can still be hard to kill, but the SDK must at least signal the same `CancelToken` used by CLI/server.
