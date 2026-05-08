# Tradeoff Map

## Why a tradeoff map is necessary

Agent harness design is full of locally reasonable choices that globally create bloat. MCP is useful. LSP is useful. Todos are useful. Subagents are useful. Plan mode is useful. Cloud agents are useful. Semantic search is useful. A database is useful. A graph runtime is useful.

The question is not whether a feature can help. The question is whether it belongs in the core, in a profile, in an extension, or in a product shell.

Tinyagent should explicitly place every capability into one of four layers:

1. Kernel primitive.
2. Profile behavior.
3. Extension/resource.
4. Product shell.

## Capability placement matrix

| Capability | Kernel | Profile | Extension/resource | Product shell | Recommendation |
| --- | ---: | ---: | ---: | ---: | --- |
| Ordered events | Yes | No | No | Consumes | Kernel primitive. |
| Tool protocol | Yes | Filters | Adds tools | Renders | Kernel primitive plus profile visibility. |
| Model providers | Contract only | Chooses variant | Adds providers | Configures | Keep provider contract tiny. |
| Policy decisions | Yes | Chooses mode | Adds rules | UI approvals | Kernel primitive. |
| Native sandbox backend | Envelope contract | May require | Backend extension | Setup UI | Keep backend pluggable. |
| ContextFS files | Yes | Chooses density | Adds sources | Browses | Kernel primitive but render-plan based. |
| MCP | No | May expose | Yes | Configures | Extension, not default. |
| LSP | No | May expose | Yes | Configures | Extension, not default. |
| Todo memory | No | May expose | Yes | Renders | Optional extension; default off. |
| Skills | Registry contract | Loads/use policy | Skill sources | UI management | Resource layer. |
| Hooks | Runner primitive | N/A | Adds hooks | Displays | Narrow kernel seam. |
| Subagents | No | Maybe profile | Extension | Product shell | Not in kernel now. |
| Cloud runs | No | No | Backend adapter | Yes | Product shell. |
| Semantic search | No | Can choose | Index backend | Config | Extension/index backend. |
| Self-improvement | No | No | Skill-draft pipeline | Review UI | Optional post-run workflow. |
| Automations | No | No | Trigger extension | Product shell | Not kernel. |
| Graph workflows | No | No | External orchestrator | Product shell | Avoid internal graph runtime. |

## Design axes

### Minimality vs capability

Pi sits at the minimality extreme. Cursor and Claude sit at the capability/product extreme. Tinyagent should be minimal in its default agent surface, but capable through extension seams.

Decision rule:

> The default profile should pay only for capabilities needed by most local coding tasks. Everything else should be discoverable, not injected.

### Safety vs interruption

Pure YOLO is fast but unsafe. Pure approval is safe but creates fatigue. Sandbox plus policy is the best current pattern.

Tinyagent should support three clear safety modes:

| Mode | Intended use | Behavior |
| --- | --- | --- |
| `tiny-pi-yolo` | Disposable/containerized workspaces | Minimal prompts, broad shell, no approvals except hard denies. |
| `tiny-safe-local` | Normal local coding | Worktree/current policy, protected paths, network denied, dirty edits gated. |
| `tiny-contained` | Hardened automation | Container/native sandbox required; no escape without approval. |

Approval modes should be product-level interaction, not hidden core state.

### Static context vs dynamic discovery

Static context gives the model orientation. Dynamic discovery gives control. Too much static context causes bloat and model anxiety. Too little static context causes aimless tool calls.

Tinyagent should keep static context to:

- system prompt;
- task;
- environment envelope;
- compact project instructions;
- compact recent observations;
- ContextFS index pointer;
- recent tool tail only when small and relevant.

Everything else should be accessible through files/context tools.

### Universal harness vs model-specific harness

Cursor’s harness writing shows that different models need different tool styles and prompts. A universal prompt is convenient but suboptimal.

Tinyagent should have a small `ModelSpec` and profile variants:

- `edit_style`: patch, str_replace, whole_file;
- `tool_protocol`: chat_completions, responses, anthropic, gemini, none;
- `context_window` and output reserve;
- `supports_parallel_tools`;
- `supports_reasoning`;
- `prompt_variant`.

The profile chooses tool visibility and prompt style accordingly.

### Events vs state machine

A graph/state-machine runtime can make orchestration explicit, but it can also bury simple flows under framework machinery. Tinyagent already has a linear loop and ordered events. That is enough for now.

Decision rule:

> If a behavior can be represented as ordered events plus files, do not introduce a graph runtime.

### Memory vs skill

Memory stores facts. Skills store reusable procedures. Skills are generally safer because they are reviewable markdown/files. Hermes’s self-evolution plan correctly ranks skill optimization as high value and lower risk.

Tinyagent should prefer:

1. run-scoped files;
2. conversation artifacts;
3. skill drafts;
4. approved installed skills;
5. only then persistent user memory.

### Product UX vs core kernel

OpenCode, Cursor, Claude, and Codex all show that product UX matters. But tinyagent’s core should not become product code.

Product shell belongs to:

- workspace registry;
- TUI/IDE/desktop integration;
- run browser;
- approval UI;
- artifact viewer;
- cloud/remote runner;
- multi-agent dashboard.

Kernel belongs to:

- run loop;
- event emission;
- policy;
- tool execution;
- context building;
- ContextFS;
- extension seams.

## Harness archetypes

### Minimal local primitive harness

Representative: Pi.

Good for:

- hackers;
- disposable workspaces;
- low bloat;
- customization;
- fast understanding.

Bad for:

- enterprise controls;
- built-in product flows;
- rich UX;
- strong default safety.

Tinyagent should offer this as `tiny-pi`.

### Productized coding workspace

Representative: Cursor, OpenCode, Claude Code.

Good for:

- daily users;
- multi-session work;
- IDE integration;
- cloud/local handoff;
- product metrics.

Bad for:

- kernel minimality;
- easy forkability;
- avoiding feature coupling.

Tinyagent should support this through runtime/protocol/product layers, not core bloat.

### Safety/protocol-first local agent

Representative: Codex.

Good for:

- trustworthy local execution;
- sandbox profiles;
- app-server clients;
- non-interactive runs.

Bad for:

- minimal tool/prompt surface;
- simplicity for hobby hacking.

Tinyagent should borrow the boundary seriousness.

### General agent framework

Representative: LangGraph, CrewAI, ADK.

Good for:

- general applications;
- workflows;
- production app scaffolding;
- durable graphs.

Bad for:

- local coding harness taste;
- tinygrad-like minimalism.

Tinyagent should not become this.

### Learning/self-improving agent

Representative: Hermes.

Good for:

- long-lived assistants;
- skill improvement;
- personalization;
- research trajectories.

Bad for:

- opacity;
- state bloat;
- hard-to-evaluate behavior.

Tinyagent should implement this only as optional skill-draft workflows.

## Decision table for tinyagent next steps

| Decision | Chosen path | Rejected path | Reason |
| --- | --- | --- | --- |
| Kernel refactor | Extract narrow hook runner first | Full state-machine rewrite | Behavior-preserving, low risk. |
| ContextFS refactor | Render plan + explicit policy | Virtual filesystem abstraction | Keeps file philosophy and safety clarity. |
| Default profile | Add `tiny-pi` | Make current profile smaller only | Lets current robust profile remain available. |
| Extensions | Resource loader + extension registry | Hardwire features into Kernel | Keeps core slim. |
| SDK | Cancellable run handle | Raw async event generator only | Better control without product bloat. |
| Memory | Skill drafts and file memory | Hidden persistent memory in core | Reviewability and minimality. |
| Multi-agent | Shared state files + product shell later | Kernel-native subagents now | Avoid premature orchestration. |
| Search | Keep rg fallback, optional semantic backend | Semantic search as core dependency | Lean default, extensible capability. |
| Protocol | Single resolver-based route implementation | Duplicated Runtime/Product handlers | Prevent safety drift. |
| Evals | Event and design metrics | Solve-rate only | Harness regressions are not always solve-rate failures. |

## The main tradeoff conclusion

Tinyagent should be “thin at rest, powerful in motion.”

Thin at rest means:

- a small core;
- a small default profile;
- few default tools;
- no automatic memory/subagents/MCP/LSP;
- no product assumptions in Kernel.

Powerful in motion means:

- extensions can add tools/context/skills/hooks;
- event traces are rich;
- artifacts preserve recoverability;
- profiles can tune behavior per model;
- product shells can run many sessions and approvals;
- evals can compare variants.

This gives the project a coherent identity rather than a collection of features.
