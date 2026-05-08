# Stage 7b — Multi-Agent Coordination Through Files

## Problem

Multi-agent work is attractive, but kernel-native subagents would add orchestration complexity too early.

## Target design

Start with file/event coordination, inspired by Cursor’s simple shared-state coordination examples and the broader Unix/file philosophy.

Shared coordination directory:

```text
.tinyagent/coordination/<session_id>/
  state.md
  tasks.jsonl
  claims.jsonl
  handoffs.jsonl
  runs/
```

Each agent is just a normal run. Coordination is a product/SDK workflow that starts multiple runs and gives each agent a scoped task plus shared state file.

## Primitives

- Shared state markdown file.
- Task queue JSONL.
- Claim/release records.
- Run summaries.
- Optional conflict detector.

## Minimal protocol

```json
{"type":"task.created","task_id":"...","summary":"..."}
{"type":"task.claimed","task_id":"...","run_id":"..."}
{"type":"handoff","from":"run_a","to":"run_b","summary":"..."}
```

## Product behavior

A TUI/product shell can show multiple active runs, shared state, and handoffs. The kernel remains unaware.

## Tests

- Two runs can read/write coordination state under policy.
- Conflicting edits are detected by normal workspace delta/git diff mechanisms.
- Shared state does not expose hidden artifacts.

## Exit criteria

- Multi-agent experiment possible without Kernel changes.
- Coordination files are inspectable.
- No graph runtime required.

## Why this matters

This gives tinyagent a path toward multi-agent workflows while preserving the minimal kernel.
