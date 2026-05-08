# Stage 7 — Product Surface Future

## Goal

Define how richer product features can grow around tinyagent without bloating the kernel.

## Why this is necessary

Cursor, Claude Code, OpenCode, and Codex show that serious coding agents need good product surfaces: terminal, IDE, desktop, cloud, multi-session, approvals, artifacts, diffs, and remote execution. Tinyagent should support these, but not by putting product code into `Kernel`.

## Substages

1. `stage_07a_tui_server_split.md`
2. `stage_07b_multi_agent_coordination_files.md`
3. `stage_07c_remote_backend_contract.md`

## Product surfaces

Potential shells:

- CLI;
- TUI;
- HTTP/SSE app server;
- IDE plugin;
- desktop UI;
- cloud runner;
- automation runner.

All should consume the same SDK/protocol concepts:

- run handles;
- events;
- approvals;
- public artifacts;
- workspaces;
- conversations;
- profile/resource config.

## Non-goals

- No product feature should require changing the model/tool loop.
- No cloud runner should require a database in the core.
- No multi-agent orchestration should be kernel-native initially.

## Exit criteria

- Product roadmap is expressed in terms of SDK/protocol capabilities.
- Core remains stable while product shells can expand.
- Multi-agent coordination starts with files/events, not a graph runtime.
