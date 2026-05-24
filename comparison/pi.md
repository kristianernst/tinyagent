# Pi Scorecard

## Source Boundary

Inspected local checkout at `/Users/kristianernst/tools/pi-extensions/pi`. Package metadata points to `https://github.com/earendil-works/pi-mono`. The checkout had unrelated untracked `ussie.md`; it was not touched.

Key files:

- `README.md`
- `packages/agent/src/harness/agent-harness.ts`
- `packages/agent/src/agent-loop.ts`
- `packages/agent/src/harness/session/session.ts`
- `packages/agent/src/harness/system-prompt.ts`
- `packages/agent/src/harness/types.ts`
- `packages/agent/src/harness/compaction/compaction.ts`

## Design Thesis

Pi is the minimal harness benchmark. It optimizes for a small, hackable TypeScript runtime with clear sessions, skills/resources, hooks, and a pure-ish loop. It is not the safety benchmark.

## Feature Read

| Area | Evidence | Design read |
| --- | --- | --- |
| Harness class | `AgentHarness` owns env/session/resources/tools, steering/follow-up queues, hooks/events, compaction, tree navigation, skill/template invocation, model/thinking changes. | Clear embedding surface with small concepts. |
| Loop | `agent-loop.ts` emits agent/turn/message/tool events, streams assistant output, validates tool args, runs before/after tool hooks, and supports steering/follow-up. | Nice separation between loop and harness shell. |
| Sessions | `harness/session/session.ts` reconstructs branch paths, model/thinking changes, compactions, custom entries, branch summaries. | Strong tree session model with simple storage semantics. |
| Skills | `system-prompt.ts` injects an XML available-skills block and tells the model to read full skills. | Similar philosophy to tinyagent skills: discoverable procedures, not hidden behavior. |
| Safety | Before/after tool hooks can block or alter calls/results. No strong built-in sandbox/profile system was found. | Good hook surface, weak default safety. |
| Provider layer | `@earendil-works/pi-ai` provides multi-provider LLM API. | Strong portability for a minimal harness. |

## Scores

| Dimension | Score |
| --- | ---: |
| Source auditability | 5.0 |
| Kernel clarity/minimality | 5.0 |
| Event/session durability | 4.0 |
| Tool execution/control | 4.0 |
| Permission/sandbox safety | 2.5 |
| Context management | 3.5 |
| Provider/runtime portability | 4.5 |
| Extensibility | 4.5 |
| Product surface/protocol | 3.5 |
| Memory/learning/automation | 2.0 |

## Strengths

- Best minimality reference.
- Branching session context is simple and useful.
- Hook points are narrow and understandable.
- Skills/resources fit a file-backed, user-owned harness.
- TypeScript embedding surface is cleaner than many product-heavy agents.

## Weaknesses

- Safety is not comparable to Codex or Claude.
- No native sandbox or rich permission profiles found.
- No MCP/LSP/product protocol depth comparable to OpenCode/Codex.
- Memory/learning/automation are intentionally sparse.

## What tinyagent Should Copy

- Keep the tiny default profile real, not just documented.
- Keep skills/resources as files the agent can inspect.
- Consider Pi's tree session model for future fork/resume UI.
- Keep the main loop understandable enough that a user can audit it.

## What tinyagent Should Avoid

- YOLO-by-default safety as the only serious mode.
- Moving product features into the kernel just because Pi exposes a clean harness API.
