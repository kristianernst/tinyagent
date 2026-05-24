# Hermes Agent Scorecard

## Source Boundary

Inspected public source fetched from `https://github.com/NousResearch/hermes-agent`, extracted at `/private/tmp/tinyagent-harness-compare/hermes-agent`.

Key files:

- `README.md`
- `agent/conversation_loop.py`
- `agent/tool_executor.py`
- `agent/tool_guardrails.py`
- `agent/memory_manager.py`
- `agent/skill_utils.py`
- `agent/codex_responses_adapter.py`
- `tools/terminal_tool.py`
- `tools/environments/base.py`
- `cron/scheduler.py`
- `gateway/session.py`

## Design Thesis

Hermes is the memory, learning, environment, and automation benchmark. It is the least minimal harness in this comparison, but it covers capabilities tinyagent mostly does not attempt yet.

## Feature Read

| Area | Evidence | Design read |
| --- | --- | --- |
| Conversation loop | `conversation_loop.py` handles model calls, tool dispatch, fallback/retry/compression, post-turn hooks, background memory, skill review nudges, and prompt caching preservation. | Ambitious but very large; not a tiny kernel. |
| Tool executor | `tool_executor.py` supports sequential/concurrent calls, up to 8 workers, interrupts, checkpoints before mutating/destructive tools, plugin pre-tool blocks, guardrails, callbacks, ordered results. | Strong execution model, more complex than tinyagent needs today. |
| Guardrails | `tool_guardrails.py` detects repeated failures, same tool/input loops, and no-progress patterns. | Good source to compare tinyagent's repeated failed command policy. |
| Memory | `memory_manager.py` supports provider-backed memory, fenced `<memory-context>`, and stream scrubbers to prevent memory-context leakage. | Best memory isolation/recall reference here. |
| Skills | `skill_utils.py` handles frontmatter, platform requirements, disabled skills, external dirs, caching, and config extraction. | Strong procedural memory surface. |
| Providers | `codex_responses_adapter.py` adapts stateless Responses API style models and preserves call IDs/prompt cache behavior. | Provider portability is taken seriously. |
| Environments | `terminal_tool.py` and `tools/environments/base.py` cover local, Docker, SSH, Singularity, Modal, Daytona, Vercel-style execution backends. | Strongest shell environment model inspected. |
| Automation | `cron/scheduler.py` has file locking, prompt assembly, injection scanning, platform delivery, profile/env overrides, MCP/toolset resolution. | Far beyond tinyagent's current scope. |
| Gateways | `gateway/session.py` tracks messaging/session context, platform/user/thread metadata, PII redaction, and dynamic prompt injection. | Product shell is broad and communication-oriented. |

## Scores

| Dimension | Score |
| --- | ---: |
| Source auditability | 5.0 |
| Kernel clarity/minimality | 1.5 |
| Event/session durability | 3.5 |
| Tool execution/control | 5.0 |
| Permission/sandbox safety | 3.5 |
| Context management | 4.0 |
| Provider/runtime portability | 5.0 |
| Extensibility | 5.0 |
| Product surface/protocol | 4.5 |
| Memory/learning/automation | 5.0 |

## Strengths

- Best persistent memory and learning story.
- Strongest scheduled automation and messaging gateway coverage.
- Broadest execution-environment abstraction.
- Real loop guardrails and checkpoint-before-mutation patterns.
- Skills are treated as procedural memory, not merely prompt snippets.

## Weaknesses

- The run loop is huge and hard to reason about as a kernel.
- The memory/learning surface increases opacity and safety risk.
- Product/gateway/automation concerns are deeply present.
- Harder to audit end-to-end than Pi or tinyagent because so much behavior is in one large loop.

## What tinyagent Should Copy

- Optional, review-gated skill-draft learning from run traces.
- Memory context fencing and output scrubbers if persistent memory is added.
- Environment abstraction vocabulary for local/container/remote shells.
- Guardrail primitives for no-progress tool loops.
- Cron injection scanning if unattended automation is ever added.

## What tinyagent Should Avoid

- Hidden self-improvement in the default run loop.
- Long-lived personal/user memory as an implicit default.
- Turning the kernel into a gateway, scheduler, and environment manager.
