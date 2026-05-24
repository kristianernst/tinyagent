# OpenAI Codex Scorecard

## Source Boundary

Inspected public source fetched from `https://github.com/openai/codex`, extracted at `/private/tmp/tinyagent-harness-compare/openai-codex`.

Key files:

- `codex-rs/core/src/session/session.rs`
- `codex-rs/core/src/session/turn.rs`
- `codex-rs/core/src/tools/orchestrator.rs`
- `codex-rs/core/src/tools/sandboxing.rs`
- `codex-rs/core/src/config/permissions.rs`
- `codex-rs/app-server/README.md`

## Design Thesis

Codex is the safety/protocol benchmark. It is heavier than tinyagent, but the source shows a mature split among session state, turn execution, permissions, sandbox policy, app-server protocol, and tool orchestration.

## Feature Read

| Area | Evidence | Design read |
| --- | --- | --- |
| Session model | `Session` and `SessionConfiguration` carry provider, approval policy, permission profile state, sandbox, cwd, workspace roots, environments, dynamic tools, history. | Product-grade state boundary. More complex than tinyagent but source-auditable. |
| Turn loop | `run_turn` handles sampling, pending input, hooks, model client session, event streaming, compaction, tool routing, and context updates. | Mature orchestration, but much larger conceptual surface than tinyagent should copy wholesale. |
| Tool orchestration | `tools/orchestrator.rs` is explicitly the central place for approvals, sandbox selection, and retry semantics. | This is the clearest design to borrow: approval -> sandbox -> attempt -> escalated retry. |
| Sandbox/permissions | `permissions.rs` has built-in read-only/workspace/danger profiles; `sandboxing.rs` compiles file/network policies and approval requirements. | Stronger safety layer than tinyagent because it combines policy and enforcement. |
| App server | `app-server/README.md` defines JSON-RPC threads, turns, items, events, approvals, file ops, permission profiles, skills/hooks/plugins/apps/MCP, memory/goal, review, remote control. | Best public protocol benchmark among inspected harnesses. |
| Memory/history | Live thread store and thread memory modes are present in `session.rs`; app-server supports resume/fork/list/read/rollback. | Strong session lifecycle product surface. |

## Scores

| Dimension | Score |
| --- | ---: |
| Source auditability | 5.0 |
| Kernel clarity/minimality | 2.5 |
| Event/session durability | 5.0 |
| Tool execution/control | 5.0 |
| Permission/sandbox safety | 5.0 |
| Context management | 4.5 |
| Provider/runtime portability | 3.5 |
| Extensibility | 5.0 |
| Product surface/protocol | 5.0 |
| Memory/learning/automation | 3.5 |

## Strengths

- Best approval/sandbox/profile architecture among the public source studied.
- App-server contract is far ahead of ad hoc CLI wrapping.
- Thread fork/resume/read/list/rollback creates a serious product session model.
- Permission profiles make safety state first-class instead of scattered flags.
- Tool orchestration is centralized enough to reason about retry and escalation.

## Weaknesses

- The core is too heavy to use as tinyagent's kernel template.
- OpenAI/product coupling is stronger than provider-neutral harnesses like OpenCode or Pi.
- Its product protocol is valuable, but copying the whole app-server shape would pull tinyagent toward product complexity.

## What tinyagent Should Copy

- A pluggable native sandbox backend with named permission profiles.
- A single tool orchestrator boundary for approval, sandbox selection, execution, retry, and event invariants.
- Generated or schema-backed app/server contracts for run/thread/event/approval APIs.
- Resume/fork/rollback semantics as product-shell features, not kernel concepts.

## What tinyagent Should Avoid

- Importing Codex's full thread/app-server scope into the core kernel.
- Treating sandbox policy, approval policy, permission profile, and product settings as scattered route-level concerns.
