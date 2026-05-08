# Stage 7c — Remote Backend Contract

## Problem

Cloud/self-hosted agents are useful for long-running or parallel work, but remote execution can easily force product complexity into the core.

## Target design

Define a remote backend contract around the same run primitives:

```python
class RunBackend(Protocol):
    def start_run(self, request: RunRequest) -> RunHandle: ...
    def get_run(self, run_id: str) -> RunSummary: ...
    def events(self, run_id: str, after_seq: int = 0) -> Iterable[Event]: ...
    def cancel(self, run_id: str, reason: str) -> bool: ...
    def artifacts(self, run_id: str) -> list[ArtifactInfo]: ...
```

Local backend wraps current `RunController` / SDK. Remote backend talks to HTTP server or future cloud runner.

## Requirements

- Same event schema.
- Same approval semantics.
- Same public artifact policy.
- Same cancellation semantics where possible.
- Explicit workspace/environment metadata.
- No assumption that remote backend has local filesystem access.

## Product features enabled

- self-hosted remote runners;
- cloud task delegation;
- long-running jobs;
- multi-agent parallel work;
- team-visible run browser.

## Tests

- Local backend and HTTP backend produce compatible event streams.
- Artifact listing/fetch behavior matches.
- Cancellation behavior matches as closely as possible.
- Approval resolution works remotely.

## Exit criteria

- Remote backend can be implemented without changing Kernel.
- Local and remote runs share schema.
- Product shell can switch backend by config.

## Why this matters

Cursor and Codex demonstrate the importance of remote/cloud/product execution. Tinyagent should support that through a backend contract, not by bloating the core loop.
