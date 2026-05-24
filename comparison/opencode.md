# OpenCode Scorecard

## Source Boundary

Inspected public source fetched from `https://github.com/sst/opencode`, extracted at `/private/tmp/tinyagent-harness-compare/opencode`.

Key files:

- `packages/opencode/src/session/processor.ts`
- `packages/opencode/src/session/tools.ts`
- `packages/core/src/permission.ts`
- `packages/opencode/src/agent/agent.ts`
- `packages/opencode/src/session/session.ts`
- `packages/opencode/src/tool/tool.ts`
- `packages/opencode/src/config/config.ts`
- `packages/opencode/src/server/server.ts`
- `packages/opencode/src/lsp/lsp.ts`
- `packages/core/src/event.ts`
- `packages/opencode/src/snapshot/index.ts`
- `packages/opencode/src/plugin/index.ts`

## Design Thesis

OpenCode is the open-source product-shell benchmark. It is broad: TUI/server/product surfaces, provider config, LSP, snapshots, plugins, agents/subagents, permissions, and session persistence. It is less tiny than tinyagent but highly useful for product architecture.

## Feature Read

| Area | Evidence | Design read |
| --- | --- | --- |
| Stream processor | `processor.ts` tracks assistant text, reasoning, tool calls, snapshots, compaction needs, usage/cost, and EventV2. | Strong event and lifecycle handling. |
| Tool routing | `session/tools.ts` resolves built-ins, transforms schemas per provider, creates `Tool.Context`, asks permissions, triggers plugin hooks, wraps MCP tools, truncates output. | Mature tool boundary. |
| Permissions | `core/src/permission.ts` provides wildcard `allow`, `deny`, `ask` rules; agents merge default/user/session permissions. | Simpler than Codex but usable and product-friendly. |
| Agents | `agent.ts` defines native `build`, `plan`, `general`, `explore`, `scout`, compaction/title agents with mode-specific permissions. | Strong profile/agent separation. |
| Sessions | `session.ts` uses SQLite-backed sessions, parent/fork info, summaries, cost/tokens/share/revert/permission/model/agent. | Serious product state model. |
| Snapshots | `snapshot/index.ts` uses a separate gitdir to track/restore/patch/diff worktree state. | The best source-backed rewind model inspected outside Codex/Claude. |
| LSP | `lsp.ts` spawns language servers and exposes diagnostics, symbols, hover, definitions, references, implementations, call hierarchy. | Clear product-shell feature tinyagent can keep as extension. |
| Plugins | `plugin/index.ts` loads internal/external plugins and keeps plugin execution deterministic. | Mature extension surface. |

## Scores

| Dimension | Score |
| --- | ---: |
| Source auditability | 5.0 |
| Kernel clarity/minimality | 2.5 |
| Event/session durability | 4.5 |
| Tool execution/control | 5.0 |
| Permission/sandbox safety | 4.0 |
| Context management | 4.0 |
| Provider/runtime portability | 5.0 |
| Extensibility | 5.0 |
| Product surface/protocol | 5.0 |
| Memory/learning/automation | 3.0 |

## Strengths

- Strongest open product surface among inspected source trees.
- Excellent snapshot/diff/restore mechanics.
- LSP integration is real and deep.
- Provider and config surface are broad.
- Agents and permissions compose better than ad hoc modes.

## Weaknesses

- Too broad to use as tinyagent's core shape.
- Permission rules are useful but less enforceable than native sandbox profiles.
- Product/session/database complexity would be bloat inside tinyagent's kernel.
- Memory/learning is not as ambitious as Hermes.

## What tinyagent Should Copy

- Git snapshot/restore as a product-shell or workspace extension.
- LSP as an optional extension that plugs into existing event/context surfaces.
- Agent/profile-specific permission defaults.
- Tool output truncation plus artifact metadata patterns.
- Server protocol discipline without adopting the whole product stack.

## What tinyagent Should Avoid

- Letting SQLite/product session concerns leak into the kernel.
- Making every useful product feature part of the default profile.
