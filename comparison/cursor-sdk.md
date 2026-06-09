# Cursor SDK Scorecard

## Source Boundary

Inspected public Cursor SDK skill/plugin source from `https://github.com/cursor/plugins/tree/main/cursor-sdk`, extracted at `/private/tmp/tinyagent-harness-compare/cursor-plugins/cursor-sdk`.

Key files:

- `skills/cursor-sdk/SKILL.md`
- `skills/cursor-sdk/references/runtime-choice.md`
- `skills/cursor-sdk/references/advanced.md`
- `skills/cursor-sdk/references/streaming.md`
- `skills/cursor-sdk/references/mcp.md`
- `skills/cursor-sdk/references/error-handling.md`
- `skills/cursor-sdk/references/auth.md`
- `skills/cursor-sdk/references/patterns.md`

Important boundary: this is source for a plugin/skill that documents `@cursor/sdk` integration. It is not the Cursor IDE or agent runtime implementation. Product conclusions about Cursor internals should be treated as closed-source unless supported by public docs or SDK behavior.

## Design Thesis

Cursor SDK is an integration surface over local and cloud Cursor agents. Its main lesson for tinyagent is lifecycle ergonomics: one-shot runs, durable agents, resume, streaming, wait/result, support checks, local-vs-cloud capability differences, and production-friendly error handling.

## Feature Read

| Area | Evidence | Design read |
| --- | --- | --- |
| Invocation patterns | `SKILL.md` defines `Agent.prompt`, `Agent.create` + `agent.send`, and `Agent.resume`. | Clear API shape tinyagent can mimic at SDK level. |
| Runtime choice | `runtime-choice.md` distinguishes local cwd execution from cloud VM/repo/PR execution and lists capability differences. | Good precedent for explicit runtime capability checks. |
| Streaming | `streaming.md` documents `run.stream()`, `run.wait()`, status/tool/assistant/thinking/request events, backpressure, cancellation, status listeners. | Strong consumer-facing stream contract. |
| Run inspection | `advanced.md` covers list/get runs, `run.conversation()`, `Agent.messages.list`, and cloud artifacts. | Good product SDK surface; local artifacts are noted as not implemented. |
| MCP | `mcp.md` covers stdio/http/sse servers, local/cloud transport differences, auth proxying, resume persistence caveats, settings-sourced MCP. | Strong integration guidance; implementation itself is closed/not in source. |
| Errors | `error-handling.md` separates startup errors (`CursorAgentError`) from run failures (`RunResult.status`). | Excellent operational taxonomy. |
| Auth | `auth.md` covers user keys, service-account keys, GitHub credentials for cloud, CI rotation patterns. | Product-grade automation guidance. |
| Subagents/artifacts | `advanced.md` says subagents and artifacts are cloud-only at v1. | Clear capability boundary. |

## Scores

| Dimension | Score |
| --- | ---: |
| Source auditability | 2.5 |
| Kernel clarity/minimality | 4.0 |
| Event/session durability | 4.0 |
| Tool execution/control | 3.0 |
| Permission/sandbox safety | 3.0 |
| Context management | 3.0 |
| Provider/runtime portability | 3.0 |
| Extensibility | 3.5 |
| Product surface/protocol | 4.0 |
| Memory/learning/automation | 3.0 |

## Strengths

- Very clear SDK lifecycle vocabulary.
- Strong local/cloud decision matrix.
- Good status/error taxonomy for production integrations.
- Runtime capability checks (`run.supports(...)`) are a practical pattern.
- Resume caveats are explicit, especially around inline MCP config.

## Weaknesses

- Full agent runtime is not source-auditable from the inspected repo.
- Provider portability is not the goal; it is Cursor's runtime.
- Local artifacts/subagents have documented gaps.
- Permissions/sandboxing are mostly product-side from this source boundary.

## What tinyagent Should Copy

- One-shot, durable-agent, and resume APIs as separate SDK paths.
- `run.stream()` plus mandatory `run.wait()` result semantics.
- Runtime capability checks and unsupported-operation reasons.
- Error taxonomy that separates "could not start" from "started and failed".
- Explicit local/cloud/runtime capability matrices if tinyagent gains remote runners.

## What tinyagent Should Avoid

- Hiding critical runtime differences behind a single options object without surfacing capability checks.
- Treating Cursor product claims as source-backed implementation facts.
