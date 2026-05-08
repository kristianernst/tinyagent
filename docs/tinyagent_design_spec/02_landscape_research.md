# Landscape Research

## Method

The comparison is organized around what each harness optimizes. The goal is not to pick a winner. The goal is to extract design pressure for tinyagent.

The sources are official docs, official project blogs, and repositories where possible. See `appendices/references.md`.

## Pi

### What Pi optimizes

Pi optimizes for ownership and minimalism. Its public messaging is unusually explicit: it is a minimal coding harness, intended to be adapted by users rather than shipped as a fixed product. It provides extensions, skills, prompt templates, themes, JSON/RPC, and SDK use, but avoids many fashionable harness features by default.

Pi’s most important ideas for tinyagent:

- four default core tools: read, write, edit, bash;
- optional grep/find/ls helpers;
- resources discovered from user/project directories;
- RPC mode for embedding;
- SDK mode for programmatic use;
- sessions that can be resumed/forked/cloned;
- no default subagents, MCP, permission popups, plan mode, or todos;
- default prompt and tools kept extremely small;
- no pretense that the harness should own the user’s workflow.

### Strengths

Pi keeps the core agent legible. That matters because the agent harness is now part of the model’s cognitive environment. Every tool name, system sentence, hidden policy rule, and product feature consumes model attention or engineering attention. Pi’s small surface makes behavior easier to understand and customize.

It also pushes state into visible files and user-controlled resources. This is aligned with tinyagent’s ContextFS direction, but Pi applies it more aggressively: if the agent needs a todo list, write one to disk; if the user wants a mode, define it as a prompt/template/resource.

### Weaknesses

Pi’s default YOLO stance and minimal safety layer are not sufficient for all tinyagent users. Tinyagent already has stronger policy, approvals, worktree handling, events, and artifacts. It should not throw that away.

Pi also does not by itself answer richer product questions: sandbox policy, IDE UX, cloud execution, protocol schemas, multi-agent workspaces, or enterprise auth.

### Tinyagent lesson

Adopt Pi as the default profile philosophy, not as the only runtime philosophy. The kernel should be Pi-small. The product/runtime layers can still expose richer protocols and safety.

## Cursor

### What Cursor optimizes

Cursor optimizes for SOTA productized coding-agent performance. Its blog posts reveal a harness philosophy that is highly relevant to tinyagent:

- dynamic context discovery rather than huge up-front prompts;
- long tool outputs written to files instead of truncated or fully prompt-injected;
- chat history accessible as files for summarization and recovery;
- skills and MCP tools discovered lazily;
- terminal sessions represented as readable files;
- per-model harness tuning;
- semantic search trained from agent traces;
- sandboxing to reduce approval fatigue;
- evals and online metrics to drive harness iteration;
- multi-agent workspace UX and cloud/local unification.

### Strengths

Cursor is strongest where Pi is intentionally sparse: product UX, model-specific harness tuning, dynamic context, safety/sandbox integration, and eval-driven iteration.

Cursor’s dynamic context discovery work is particularly important. It shows a clear trend: the model should not receive all possible context. It should receive enough orientation and then pull more through tools/files. This maps almost directly to tinyagent’s ContextFS and context source system.

Cursor’s sandboxing work also gives a useful standard. Approvals alone cause fatigue. A sandbox lets the agent proceed safely inside boundaries and ask only when it must cross them. Tinyagent’s policy layer is good, but native sandboxing remains an area where Cursor/Codex are ahead.

### Weaknesses

Cursor is a product, not a tiny kernel. Its best ideas can become bloat if copied directly. Multi-agent workspaces, cloud agents, automations, semantic search, and sandboxing are important, but they are not all kernel primitives.

### Tinyagent lesson

Adopt Cursor’s dynamic context and eval discipline. Do not adopt Cursor’s product complexity into the core. Represent complex product features as shells around the kernel.

## Codex / Codex.rs

### What Codex optimizes

Codex CLI and Codex.rs optimize for a local terminal coding agent with strong sandbox/approval controls, cross-platform support, non-interactive execution, MCP support, and a structured app-server protocol. Codex.rs is especially relevant because it is a concrete implementation of an agent harness in a systems language.

Important concepts:

- config profiles with approval and sandbox modes;
- native sandboxing by OS;
- app-server protocol for TUI and remote clients;
- command execution and MCP tooling;
- AGENTS.md instruction loading;
- non-interactive `exec` mode;
- tool/requestUserInput and approval-like events in the app-server surface.

### Strengths

Codex has a strong safety/protocol posture. Its sandbox documentation is explicit about boundaries and approvals. Its app-server model is a good comparison point for tinyagent’s HTTP/SSE runtime.

The app-server direction matters because serious agent clients need a stable protocol, not just a CLI wrapper. Tinyagent already has `/v1` endpoints and event streaming, but the route duplication and partly hand-written schema are weaker than Codex’s generated/contract-driven direction.

### Weaknesses

Codex is heavier than Pi. It is a product-grade agent harness, not a minimal hackable kernel. It can inspire tinyagent’s safety and protocol boundaries, but not its default surface.

### Tinyagent lesson

Use Codex as the safety/protocol benchmark. Keep tinyagent’s kernel simpler than Codex, but make the public event and route contracts more disciplined.

## Claude Code and Claude Agent SDK

### What Claude optimizes

Claude Code optimizes for an agentic coding assistant spanning CLI, IDE, desktop, browser, cloud tasks, MCP, memory, skills, hooks, and multiple agents. The Agent SDK exposes similar capabilities for applications.

Important concepts:

- permission modes: default, accept edits, plan, auto, don’t ask, bypass;
- allow/ask/deny rules;
- SDK permission callbacks such as `canUseTool`;
- composable CLI usage through Unix-like piping;
- built-in tool categories including read/write/edit/bash/grep/glob/web;
- hooks that can intervene at multiple lifecycle points;
- strong product-level UX around IDE and desktop integration.

### Strengths

Claude’s permission and hook systems are richer than tinyagent’s current in-process hook protocol. Its SDK permission ordering is a useful model: hooks first, deny rules, mode checks, allow rules, callback/human resolution.

Claude also preserves the value of CLI composability. Its examples treat the agent as a Unix-style command that can be piped into and out of other tools. Tinyagent should keep this spirit.

### Weaknesses

Claude’s feature surface is broad. For tinyagent, copying the product layer would violate the minimal design goal. Hook richness should not become hook sprawl.

### Tinyagent lesson

Adopt a cleaner hook runner and approval-aware SDK, but keep hooks as narrow lifecycle seams. Do not make hooks a general hidden control plane.

## OpenCode

### What OpenCode optimizes

OpenCode optimizes for open-source, provider-agnostic product surfaces: terminal, desktop, IDE, multi-session operation, LSP support, shareable sessions, many providers, and custom tools.

Important concepts:

- multiple sessions on one project;
- LSP support;
- provider agnosticism through Models.dev / AI SDK style integrations;
- custom tools in project/global directories;
- agents and subagents with tool access modes;
- client/server architecture;
- privacy-first stance.

### Strengths

OpenCode is a good product-surface benchmark. It shows that a coding agent can stay provider-agnostic and still ship an integrated terminal/IDE/desktop experience.

Its custom tool model is relevant: tools are ordinary code modules in project or global paths, and they can override built-ins. Tinyagent’s extension system should support a similarly lightweight project-local extension path without requiring users to write a framework plugin.

### Weaknesses

OpenCode’s broad UX and agent/subagent configuration can become too product-heavy for tinyagent’s core. It also does not define the same kind of minimalist philosophical anchor as Pi.

### Tinyagent lesson

Use OpenCode as a product-shell benchmark, especially for provider agnosticism, LSP, sessions, and custom tools. Keep those outside the kernel where possible.

## Hermes Agent

### What Hermes optimizes

Hermes optimizes for self-improvement and persistent learning. It emphasizes skill creation from experience, skill improvement during use, persistent memory and user model, conversation search, automations, subagents, and research/optimization pipelines.

Important concepts:

- closed learning loop;
- skill creation and improvement;
- persistent knowledge base and user model;
- human-review and rollback gates in self-evolution plans;
- offline optimization pipelines using traces/evals rather than model-weight training;
- high-value/low-risk optimization starts with skills, not core code.

### Strengths

Hermes is the best comparison for memory and self-improvement. It shows how an agent can turn traces into better future behavior. Its self-evolution plan is also sober: skill optimization is lower risk than tool-description or code evolution, and human review/rollback gates matter.

### Weaknesses

Hermes is intentionally more ambitious than tinyagent’s current lean goal. Persistent user modeling and self-improvement can easily make the system opaque and bloated.

### Tinyagent lesson

Implement learning only as an optional, file-backed, review-gated skill-draft pipeline. Do not put self-improvement into the default run loop.

## OpenAI Agents SDK

### What it optimizes

The OpenAI Agents SDK is a general agent SDK rather than a coding harness. It focuses on agent definitions, running agents, tools, MCP, guardrails, handoffs, tracing, state/results, and human review.

### Strengths

It sets expectations for a modern SDK: typed results, tool integration, guardrails, tracing, and human review. Tinyagent’s current SDK is much thinner and should be upgraded.

### Weaknesses

It is not a local coding harness. It does not directly solve local workspace policy, git diffs, ContextFS, or shell execution semantics.

### Tinyagent lesson

Use it as an SDK ergonomics benchmark, not as a harness architecture benchmark.

## LangGraph, AutoGen, CrewAI, Google ADK

### What they optimize

These frameworks optimize for broader agent application development rather than local coding harness minimalism.

- LangGraph emphasizes durable execution, state checkpoints, memory, human-in-the-loop, and graph-shaped workflows.
- AutoGen popularized multi-agent conversational patterns, though older versions entered maintenance mode while newer directions evolved.
- CrewAI emphasizes production multi-agent systems, roles, guardrails, knowledge, and observability.
- Google ADK emphasizes code-first, model/deployment-agnostic agent development, enterprise workflows, and richer toolsets such as skill toolsets.

### Strengths

These frameworks are useful for studying durability, human-in-loop, graph orchestration, memory, and enterprise deployment.

### Weaknesses

They are not the right default shape for tinyagent. A graph framework inside tinyagent would be a mistake unless it emerges from a concrete product need and remains outside the kernel.

### Tinyagent lesson

Borrow durable-execution and human-input ideas at the event/protocol level. Do not turn tinyagent into a graph framework.

## Summary comparison

| Harness | Core philosophy | Best idea to borrow | Main risk if copied too literally |
| --- | --- | --- | --- |
| Pi | Minimal primitives, user-owned harness | Tiny default profile, resource loader, RPC/SDK simplicity | Too little safety by default |
| Cursor | Productized SOTA harness | Dynamic context, sandboxing, eval-driven iteration | Product complexity invading kernel |
| Codex | Local terminal harness with strong sandbox/protocol | Approval/sandbox profiles, app-server contract | Heavier than tinyagent core should be |
| Claude Code | Rich agent UX plus hooks/permissions | Permission callback model and lifecycle hooks | Hook/feature sprawl |
| OpenCode | Open provider-agnostic product surface | Custom tools, LSP, multi-session product shell | Too broad for kernel |
| Hermes | Self-improving persistent agent | Review-gated skill learning from traces | Opaque memory and self-modification |
| OpenAI Agents SDK | General agent SDK | Typed results, guardrails, tracing, human review | Not local-code-specific |
| LangGraph/ADK/etc. | Application frameworks | Durable state and human-in-loop patterns | Framework bloat |

## The synthesis for tinyagent

Tinyagent’s best target is not one of these systems. It is a synthesis:

- Pi’s minimal default surface;
- Cursor’s dynamic context and eval discipline;
- Codex’s sandbox/approval/protocol seriousness;
- Claude’s permission callback and hook lifecycle clarity;
- OpenCode’s custom-tool/provider/product extensibility;
- Hermes’s optional skill learning through review gates;
- LangGraph’s durable-state idea, but implemented as files/events, not a graph runtime.
