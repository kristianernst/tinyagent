# Scoreboard

Scores are 1 to 5 and are intentionally not summed into a single winner. A harness can be excellent for product UX and still be the wrong kernel model for tinyagent.

## Design Score Matrix

| Harness | Source audit | Minimal core | Events/session | Tool control | Safety/sandbox | Context | Provider/runtime | Extensibility | Product/protocol | Memory/automation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| tinyagent | 5.0 | 5.0 | 5.0 | 3.5 | 3.5 | 4.5 | 4.0 | 4.0 | 2.5 | 2.5 |
| OpenAI Codex | 5.0 | 2.5 | 5.0 | 5.0 | 5.0 | 4.5 | 3.5 | 5.0 | 5.0 | 3.5 |
| Pi | 5.0 | 5.0 | 4.0 | 4.0 | 2.5 | 3.5 | 4.5 | 4.5 | 3.5 | 2.0 |
| OpenCode | 5.0 | 2.5 | 4.5 | 5.0 | 4.0 | 4.0 | 5.0 | 5.0 | 5.0 | 3.0 |
| Hermes | 5.0 | 1.5 | 3.5 | 5.0 | 3.5 | 4.0 | 5.0 | 5.0 | 4.5 | 5.0 |
| Cursor SDK | 2.5 | 4.0 | 4.0 | 3.0 | 3.0 | 3.0 | 3.0 | 3.5 | 4.0 | 3.0 |
| Claude Code/SDK | 2.5 | 3.0 | 4.5 | 4.5 | 4.5 | 4.5 | 2.5 | 5.0 | 5.0 | 4.5 |

## Category Leaders

| Category | Leader(s) | Why |
| --- | --- | --- |
| Minimal kernel | tinyagent, Pi | Small default concepts, readable core, few required product assumptions. |
| Safety/sandbox | OpenAI Codex | Named permission profiles plus sandbox-backed enforcement and approval orchestration. |
| Product protocol | OpenAI Codex, OpenCode, Claude | Codex app-server is the strongest public protocol; OpenCode and Claude expose broad product surfaces. |
| SDK lifecycle | Cursor SDK, Claude SDK | Clear one-shot/stateful/resume patterns, stream/wait split, dynamic control, error taxonomy. |
| Snapshots/rewind | OpenCode, Claude SDK, Codex | OpenCode has source-backed git snapshots; Claude exposes file checkpoint rewind; Codex has mature thread/file controls. |
| Memory/learning | Hermes | Closed learning loop, persistent memory, skills, cron, messaging, and user modeling. |
| Provider portability | OpenCode, Hermes, Pi, tinyagent | These are not single-model SDKs; OpenCode and Hermes are broadest. |
| Dynamic context | tinyagent, Codex, OpenCode, Claude | tinyagent's ContextFS is strong; others have richer product integration. |

## Tinyagent Position

Tinyagent is already strong where a kernel should be strong:

- event durability;
- artifact boundaries;
- context files;
- policy decisions;
- evidence-based finish gates;
- provider abstraction.

Tinyagent is behind where product-grade harnesses invest heavily:

- native sandboxing;
- app/server protocol maturity;
- session fork/list/read product UX;
- snapshot/rewind;
- IDE/cloud/product shells;
- persistent memory and automation.

The design move is not to copy the largest systems. The move is to keep tinyagent's kernel small and make the missing product-grade capabilities attach through explicit seams.
