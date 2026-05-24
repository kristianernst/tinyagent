# Claude Code / Claude Agent SDK Scorecard

## Source Boundary

Inspected:

- `https://github.com/anthropics/claude-code`, extracted at `/private/tmp/tinyagent-harness-compare/claude-code`
- `https://github.com/anthropics/claude-code-sdk-python`, extracted at `/private/tmp/tinyagent-harness-compare/claude-code-sdk-python`

Key files:

- `claude-code/README.md`
- `claude-code/examples/settings/README.md`
- `claude-code/plugins/README.md`
- `claude-code-sdk-python/README.md`
- `claude-code-sdk-python/src/claude_agent_sdk/types.py`
- `claude-code-sdk-python/src/claude_agent_sdk/client.py`
- `claude-code-sdk-python/src/claude_agent_sdk/query.py`
- `claude-code-sdk-python/src/claude_agent_sdk/_internal/transport/subprocess_cli.py`
- `claude-code-sdk-python/src/claude_agent_sdk/_internal/session_store.py`
- `claude-code-sdk-python/src/claude_agent_sdk/_internal/session_resume.py`
- `claude-code-sdk-python/examples/hooks.py`
- `claude-code-sdk-python/examples/tool_permission_callback.py`
- `claude-code-sdk-python/e2e-tests/test_dynamic_control.py`

Important boundary: the Claude Code core CLI implementation is not public in the inspected source. The Python Agent SDK, examples, settings, and plugins are source-auditable.

## Design Thesis

Claude Code is a broad product harness, and the Python Agent SDK is a mature embedding layer over the CLI. The public SDK source is especially useful for permissions, hooks, subprocess lifecycle, session stores, context usage, MCP status, and dynamic control.

## Feature Read

| Area | Evidence | Design read |
| --- | --- | --- |
| Query modes | `query.py` provides one-shot/unidirectional streaming; `client.py` provides interactive bidirectional `ClaudeSDKClient`. | Clean split between simple automation and stateful sessions. |
| Permissions | `types.py` defines modes `default`, `acceptEdits`, `plan`, `bypassPermissions`, `dontAsk`, `auto`; `can_use_tool` callbacks return allow/deny with optional input updates. | Strong approval surface, richer than tinyagent's current SDK callbacks. |
| Hooks | `types.py` defines PreToolUse, PostToolUse, PostToolUseFailure, UserPromptSubmit, Stop, SubagentStart/Stop, PreCompact, Notification, PermissionRequest. | Best source-auditable hook taxonomy in this comparison. |
| Sandbox | `SandboxSettings` controls Bash sandboxing; settings examples clarify it applies to Bash, not all tools. | Better than no sandbox, but not universal enforcement for all tool categories. |
| MCP | `McpServerConfig` covers stdio, SSE, HTTP, SDK/in-process servers; client can get/reconnect/toggle MCP status. | Strong MCP integration, including in-process SDK tools. |
| Dynamic control | `client.py` supports `interrupt`, `set_permission_mode`, `set_model`, `rewind_files`, `stop_task`, `get_mcp_status`, `get_context_usage`. | Very strong runtime control surface. |
| Sessions | `SessionStore` mirrors JSONL transcripts to external stores; resume materializes store data into temp `CLAUDE_CONFIG_DIR`; subagent transcripts are handled. | Strong external persistence design. |
| Plugins | `claude-code/plugins/README.md` documents plugins with commands, agents, skills, hooks, MCP servers. | Broad product extension model. |
| Subprocess | `subprocess_cli.py` bundles/falls back to CLI, builds stream-json command, tracks child processes, handles graceful close. | Good example of robust CLI-as-engine SDK wrapping. |

## Scores

| Dimension | Score |
| --- | ---: |
| Source auditability | 2.5 |
| Kernel clarity/minimality | 3.0 |
| Event/session durability | 4.5 |
| Tool execution/control | 4.5 |
| Permission/sandbox safety | 4.5 |
| Context management | 4.5 |
| Provider/runtime portability | 2.5 |
| Extensibility | 5.0 |
| Product surface/protocol | 5.0 |
| Memory/learning/automation | 4.5 |

## Strengths

- Richest public hook and permission callback vocabulary.
- Strong SDK control surface for model/permission changes, interrupts, MCP status, context usage, and file rewind.
- Session store protocol is thoughtful about local durability plus external mirroring.
- Plugins combine commands, agents, skills, hooks, and MCP.
- In-process SDK MCP tools are a practical way to avoid subprocess sprawl.

## Weaknesses

- Core CLI implementation is not public in the inspected source.
- Provider portability is intentionally Claude-centric.
- Bash sandbox settings do not cover all tools.
- Product breadth is far beyond what tinyagent should place in its kernel.

## What tinyagent Should Copy

- A richer hook taxonomy, but only at narrow lifecycle seams.
- `can_use_tool`-style callbacks that can allow, deny, or update input.
- Context usage introspection as a first-class SDK call.
- Session-store mirroring for external persistence without requiring the kernel to own the database.
- In-process custom tools as an MCP-compatible convenience layer.

## What tinyagent Should Avoid

- Treating hooks as an unbounded hidden control plane.
- Copying Claude's product/plugin breadth into the default profile.
- Claiming universal sandboxing if only shell execution is sandboxed.
