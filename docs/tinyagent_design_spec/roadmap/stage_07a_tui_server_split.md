# Stage 7a — TUI / Server Split

## Problem

The current CLI and server are functional but not yet a cohesive product surface. Before building a richer TUI/IDE/desktop layer, the split between kernel, SDK, runtime server, and UI needs to be clear.

## Target design

Layering:

```text
Kernel: run loop, events, policy, tools.
SDK: run handles, approvals, results.
Runtime server: HTTP/SSE protocol over SDK/controller.
TUI/IDE/Desktop: UI clients consuming events/artifacts/approvals.
```

## TUI principles

- stream public/user events by default;
- show debug/internal events only when enabled;
- show approvals as actionable prompts;
- show public artifacts and final diff;
- allow cancellation;
- allow profile/resource selection;
- do not require product home for one-off local runs.

## Server principles

- no duplicated route policy;
- v1 schema stable;
- product mode uses workspace resolver;
- single-workspace mode uses trivial resolver;
- artifact visibility enforced centrally.

## Tests

- TUI can consume SDK event stream in-process.
- Server can consume same run controller semantics.
- Approval flow works in both.
- Cancellation works in both.

## Exit criteria

- UI work does not modify Kernel.
- Server route behavior is shared and tested.
- CLI remains useful as a Unix-style command.

## Why this matters

OpenCode/Cursor/Claude show product surface importance. But tinyagent should earn product features through a stable SDK/protocol, not by hardwiring UI assumptions into the core.
