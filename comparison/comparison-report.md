# Agent Harness Comparison Report

Generated 2026-05-24. Sources and source boundaries are listed in [sources.md](sources.md). Detailed per-harness notes are in:

- [tinyagent.md](tinyagent.md)
- [openai-codex.md](openai-codex.md)
- [pi.md](pi.md)
- [opencode.md](opencode.md)
- [hermes.md](hermes.md)
- [cursor-sdk.md](cursor-sdk.md)
- [claude-code.md](claude-code.md)

Feature coverage is catalogued in [feature-taxonomy.md](feature-taxonomy.md), and numeric design scores are in [scoreboard.md](scoreboard.md).

## Executive Summary

Tinyagent should stay a small event-sourced kernel, not become a product framework. Its current strengths are real: events are structured, large payloads are artifacts, ContextFS makes model-readable context explicit, policy decisions are inspectable, and profiles let behavior vary without changing the kernel.

The strongest external pressure is safety and protocol maturity:

- OpenAI Codex is the benchmark for native sandboxing, permission profiles, approval orchestration, and app-server protocol.
- OpenCode is the benchmark for open-source product shell breadth: LSP, snapshots, provider breadth, server architecture, plugins, and multi-session state.
- Pi is the benchmark for keeping the core harness small and user-owned.
- Hermes is the benchmark for persistent memory, learning, cron, messaging, subagents, and broad shell environments.
- Cursor SDK is the benchmark for a production SDK lifecycle over local/cloud agents.
- Claude Agent SDK is the benchmark for hooks, permission callbacks, session-store mirroring, dynamic control, and SDK-managed CLI subprocess execution.

The main conclusion: tinyagent should copy boundaries, not bulk.

## Current Tinyagent Read

Tinyagent's best architectural asset is the event/artifact split. `tinyagent/core/events.py` defines a broad durable event taxonomy and separate live-only deltas. `tinyagent/core/state.py` and artifact helpers keep large tool payloads out of event metadata. `tinyagent/core/contextfs.py` turns run state, diffs, tool docs, and context refs into a file surface the model can read.

This makes tinyagent unusually well positioned for replay, evals, UI, and product shells without forcing those product shells into the kernel.

The biggest gap is enforcement. `tinyagent/core/policy.py` is a strong classifier-first local policy, but its docstring is explicit: it is not a sandbox. Codex and Claude show that serious local execution needs named permission profiles plus OS/container/network/filesystem enforcement. Tinyagent can keep policy as a kernel primitive, but sandboxing should become a pluggable backend.

## Harness Lessons

### OpenAI Codex

Codex should be treated as the safety/protocol reference. Its source centralizes approval plus sandbox retry in `tools/orchestrator.rs`, compiles named permission profiles in `config/permissions.rs`, and exposes threads/turns/items/approvals/files/permissions through `app-server/README.md`.

For tinyagent, the borrow is:

- named permission profiles;
- approval -> sandbox -> execution -> escalated retry as one orchestrator boundary;
- generated/schema-backed server contracts;
- thread resume/fork/rollback as product-shell features.

Do not copy Codex's full product state into the kernel.

### Pi

Pi proves that a coding harness can remain understandable. `AgentHarness`, `agent-loop.ts`, tree sessions, skills, templates, steering, and compaction are small enough to audit. It is not a safety model, but it is a strong taste model.

For tinyagent, the borrow is:

- keep a true tiny default profile;
- use skills/resources as visible files;
- consider tree sessions for future fork/resume UI;
- keep the main loop legible.

Do not inherit Pi's lack of sandbox/profile safety.

### OpenCode

OpenCode is the best open product-shell comparison. Its session processor, tool router, permission rules, agents, server, LSP service, snapshot service, and plugin loader show what a full open coding-agent product looks like.

For tinyagent, the borrow is:

- git snapshot/restore as a workspace extension;
- LSP as an optional extension;
- agent/profile-specific permission defaults;
- product server discipline.

Do not let SQLite/session/product concerns become kernel dependencies.

### Hermes

Hermes is the ambitious long-lived assistant comparison. It has broad environment backends, concurrent tool execution, checkpoints, loop guardrails, persistent memory, skills, cron, messaging gateways, and post-turn learning hooks.

For tinyagent, the borrow is:

- optional review-gated skill-draft learning;
- memory context fencing and stream scrubbers if memory is added;
- environment vocabulary for local/container/remote shells;
- no-progress guardrail primitives;
- cron prompt injection scanning if unattended automation is added.

Do not put hidden self-improvement or user modeling in the default loop.

### Cursor SDK

The source-auditable part is the plugin/skill documentation for `@cursor/sdk`, not Cursor's implementation. Still, the SDK vocabulary is excellent: `Agent.prompt`, `Agent.create`, `agent.send`, `Agent.resume`, `run.stream`, `run.wait`, `run.supports`, local/cloud capability differences, and distinct startup-vs-run failure handling.

For tinyagent, the borrow is:

- one-shot, durable-agent, and resume APIs as distinct SDK paths;
- stream plus terminal wait result;
- unsupported-operation reasons;
- runtime capability matrices;
- error taxonomy separating failed startup from failed execution.

### Claude Code / Agent SDK

Claude's public SDK source is strong even though the core CLI is not public. `ClaudeAgentOptions`, `ClaudeSDKClient`, session stores, hooks, permission callbacks, MCP status, context usage, file rewind, task stop, and subprocess cleanup are all useful references.

For tinyagent, the borrow is:

- a richer but narrow hook taxonomy;
- tool permission callbacks that can allow, deny, or update input;
- context usage introspection;
- session-store mirroring without making the kernel own a database;
- in-process custom tools through an MCP-compatible interface.

Do not claim universal sandboxing if only shell commands are sandboxed, and do not let hooks become an invisible control plane.

## Feature Priorities For Tinyagent

### 1. Native Sandbox Backend

Tinyagent should add a pluggable sandbox envelope before expanding product features. The current policy layer is good but advisory. The target shape should resemble:

- `read-only`;
- `workspace-write`;
- `contained-yolo`;
- `danger-full-access`;
- optional network policy;
- explicit unsupported-platform behavior.

The kernel should keep producing `policy.evaluated`, `approval.requested`, and tool events. The sandbox backend should be a policy/execution envelope, not a new orchestration framework.

### 2. Tool Orchestrator Cleanup

Codex and OpenCode both show the value of a central tool execution boundary. Tinyagent should keep its existing event semantics but isolate:

- hidden/unknown tool handling;
- policy evaluation;
- approval;
- sandbox selection;
- before/after hooks;
- execution;
- output normalization/artifacting;
- workspace delta capture;
- step closure.

This is a narrow extraction, not a workflow engine.

### 3. Public Runtime Protocol

Tinyagent should make its HTTP/SSE or app-server contract more disciplined:

- stable run/thread/session IDs;
- event schemas;
- artifact visibility rules;
- approval request/resolve endpoints;
- run list/read/cancel;
- optional fork/resume later.

Codex is the best benchmark here, but tinyagent can keep a smaller surface.

### 4. Snapshot/Rewind As Extension

OpenCode and Claude both make rewind/restoration product-real. Tinyagent already records diffs and deltas; the next step is a workspace snapshot extension:

- before-edit snapshot;
- changed-path tracking;
- restore/rewind command;
- event/artifact evidence;
- disabled by default if workspace is not suitable.

This should be outside the minimal default profile.

### 5. SDK Lifecycle Upgrade

Tinyagent's SDK exists, but Cursor and Claude show a richer expected lifecycle:

- `Agent.prompt(...)` one-shot;
- `Agent.create(...)` for durable stateful runs;
- resume/list/read runs;
- `run.stream()` and `run.wait()`;
- `run.supports(...)`;
- startup error vs run error distinction;
- context usage and MCP status when relevant.

### 6. Optional Learning, Not Default Memory

Hermes should not be copied into the loop. The safe tinyagent version is:

- post-run trace review;
- draft a skill file;
- require explicit user review/install;
- record provenance and test evidence;
- no hidden user model by default.

## Capability Placement

| Capability | Put it in |
| --- | --- |
| Ordered events | Kernel |
| Artifact references | Kernel |
| Policy decisions | Kernel |
| Approval request/resolution | Kernel plus product UI |
| Sandbox backend | Pluggable execution envelope |
| ContextFS | Kernel |
| MCP/LSP | Extensions |
| Snapshots/rewind | Workspace extension/product shell |
| Skills | Resource layer/profile policy |
| Hooks | Narrow kernel seam |
| Subagents | Extension/product shell |
| Cloud runners | Product shell |
| Persistent memory | Optional reviewed resource |
| Skill learning | Offline/review-gated workflow |
| Cron/messaging | Product shell |

## Final Recommendation

The strongest path is:

1. Preserve tinyagent's event/artifact/context kernel.
2. Add Codex-style permission profiles and a real sandbox backend.
3. Extract a narrow tool orchestrator that protects event invariants.
4. Stabilize a small runtime protocol before adding product shell features.
5. Add OpenCode-style snapshots and LSP as extensions.
6. Upgrade the SDK lifecycle using Cursor/Claude patterns.
7. Keep Hermes-style learning optional, file-backed, and review-gated.

This keeps tinyagent competitive on harness quality without sacrificing the small-core design that makes it worth having.
