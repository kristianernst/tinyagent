# Feature Taxonomy

This is the shared vocabulary used by the scorecards. It tries to cover the practical feature surface of modern coding-agent harnesses, not just the features tinyagent already has.

## Runtime And Session

| Feature | What counts |
| --- | --- |
| Run/thread identity | Stable IDs for a run, thread, session, or agent, with enough metadata to resume or inspect later. |
| Durable transcript | Messages and tool results persisted outside process memory. |
| Event stream | Structured stream of assistant, tool, status, usage, and lifecycle events. |
| Replay | Ability to inspect or reconstruct a past run from persisted state. |
| Fork/branch | Ability to continue from old history on a new branch/session. |
| Interrupt/cancel | User or API can stop in-flight work. |
| Usage/cost accounting | Runtime reports token, cost, model, or duration usage. |
| Context compaction | History can be summarized or compacted before overflow. |

## Workspace And Artifacts

| Feature | What counts |
| --- | --- |
| Workspace boundary | Runtime knows the intended project roots and rejects or gates escapes. |
| Dirty worktree handling | Existing user changes are detected and protected. |
| Diff tracking | Runtime captures before/after file changes or final diff. |
| Snapshot/rewind | Runtime can restore or rewind modified files. |
| Artifact store | Large payloads live in files or artifact storage instead of hidden prompt state. |
| Context files | The model can read curated context files or references. |
| Search/index | Code search, semantic search, or indexed context retrieval. |

## Tools And Execution

| Feature | What counts |
| --- | --- |
| Built-in code tools | Read, write/edit, patch, shell, search, git, web, or similar. |
| Tool lifecycle | Structured start/delta/result/error events around tool calls. |
| Parallel tools | More than one tool can execute safely in a single step. |
| Tool output normalization | Long outputs are truncated, referenced, summarized, or artifacted consistently. |
| Before/after hooks | Deterministic code can inspect, alter, block, or enrich tool calls/results. |
| Custom tools | Users can add new tools without modifying the core runtime. |
| MCP | Model Context Protocol support for external tools/resources. |
| LSP | Language-server diagnostics/symbols/definitions/references. |
| Shell environment model | Clear local/container/remote execution semantics. |

## Safety And Permissions

| Feature | What counts |
| --- | --- |
| Policy engine | Allow/deny/ask decisions are structured, not prompt-only. |
| Permission profiles | Named modes such as read-only, workspace-write, full access, plan, yolo. |
| Human approval | Runtime can ask a human or host app before risky actions. |
| Auto review/classifier | Runtime can use a reviewer/model/classifier before approval. |
| Native sandbox | OS/container/network/filesystem enforcement, not just policy text. |
| Secret protection | Env files, credentials, and external exfiltration paths are gated. |
| Network control | Network operations can be denied, allowed, proxied, or sandboxed. |
| Loop guardrails | Repeated failing commands/tool loops can be halted. |

## Extensibility And Product Surfaces

| Feature | What counts |
| --- | --- |
| Skills/resources | Markdown or file-backed reusable procedures discoverable by the agent. |
| Plugins | Installable extension bundles with commands, hooks, agents, tools, or settings. |
| Custom agents/subagents | Named specialized agents can be invoked or run concurrently. |
| SDK embedding | External programs can run/control the harness directly. |
| App/server protocol | Stable API for UI clients, IDEs, or remote controllers. |
| CLI/TUI | Terminal-native product surface. |
| IDE/desktop/web | Integrated product shells beyond terminal. |
| Cloud runtime | Hosted or remote execution that can outlive the local process. |
| PR automation | Runtime can create/update branches or PRs directly. |

## Memory, Learning, And Automation

| Feature | What counts |
| --- | --- |
| Persistent memory | Facts/preferences survive across sessions. |
| User model | Memory models the user or long-running relationship. |
| Skill evolution | Runtime drafts, installs, or improves reusable skills. |
| Scheduled automation | Cron/scheduled tasks run unattended. |
| Messaging gateway | Agent can operate over Slack/Telegram/Discord/email/etc. |
| Eval/tracing loop | Traces, metrics, or evals drive harness iteration. |

## Coverage Matrix

Legend: `Full` = source-backed substantial implementation, `Partial` = present but thin/limited/closed in key areas, `No` = not found, `Closed` = product likely has it but implementation not source-auditable here. A few cells use short descriptors where the answer is capability-shaped rather than binary.

| Feature | tinyagent | OpenAI Codex | Pi | OpenCode | Hermes | Cursor SDK | Claude Code/SDK |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Run/thread identity | Full | Full | Full | Full | Full | Full | Full |
| Durable transcript | Full | Full | Full | Full | Full | Full | Full |
| Event stream | Full | Full | Full | Full | Partial | Full | Full |
| Replay/inspection | Full | Full | Partial | Full | Partial | Full | Full |
| Fork/branch | Partial | Full | Full | Partial | Partial | Full | Full |
| Interrupt/cancel | Full | Full | Partial | Full | Partial | Full | Full |
| Usage/cost accounting | Full | Full | Partial | Full | Partial | Full | Full |
| Context compaction | Partial | Full | Full | Full | Full | Closed | Full |
| Workspace boundary | Full | Full | Partial | Full | Full | Partial | Full |
| Dirty worktree handling | Full | Full | No | Partial | Partial | Closed | Partial |
| Diff tracking | Full | Full | Partial | Full | Partial | Partial | Partial |
| Snapshot/rewind | Partial | Full | No | Full | Full | Closed | Full |
| Artifact store | Full | Full | No | Partial | Partial | Cloud-only | Partial |
| Context files | Full | Full | Full | Full | Full | Closed | Full |
| Search/index | Full | Full | Partial | Full | Full | Closed | Full |
| Built-in code tools | Full | Full | Full | Full | Full | Closed | Full |
| Tool lifecycle | Full | Full | Full | Full | Full | Full | Full |
| Parallel tools | Partial | Full | Full | Full | Full | Closed | Full |
| Tool output normalization | Full | Full | Partial | Full | Partial | Full | Full |
| Before/after hooks | Full | Full | Full | Full | Full | Closed | Full |
| Custom tools | Partial | Full | Full | Full | Full | MCP-only | Full |
| MCP | Full | Full | No | Full | Full | Full | Full |
| LSP | Full | Partial | No | Full | No | Closed | No |
| Shell environment model | Local-only | Local/remote/sandbox | Local-only | Local/product | Local/Docker/SSH/cloud backends | Local/cloud | Local/SDK subprocess + sandbox |
| Policy engine | Full | Full | Hook-level | Full | Full | Closed | Full |
| Permission profiles | Full | Full | No | Full | Partial | Closed | Full |
| Human approval | Full | Full | Hook-level | Full | Full | Closed | Full |
| Auto review/classifier | Partial | Full | No | Partial | Partial | Closed | Full |
| Native sandbox | No | Full | No | Partial | Environment-level | Closed | Bash-only sandbox settings |
| Secret protection | Full | Full | No | Partial | Partial | Closed | Full |
| Network control | Full policy, no sandbox | Full | No | Partial | Partial | Closed | Full |
| Loop guardrails | Full | Partial | No | Full | Full | Closed | Partial |
| Skills/resources | Full | Full | Full | Partial | Full | No | Full |
| Plugins | Partial | Full | Partial | Full | Full | No | Full |
| Subagents | No | Full | No | Full | Full | Cloud-only | Full |
| SDK embedding | Full | App-server/protocol | Full | HTTP/server | Partial | Full | Full |
| App/server protocol | Partial | Full | Partial | Full | Partial | Cloud API/SDK | SDK + CLI protocol |
| CLI/TUI | Partial | Full | Full | Full | Full | No | Full |
| IDE/desktop/web | No | Full | Web UI package | Full | Gateways | Cursor product closed | Full |
| Cloud runtime | No | Environments/remote support | No | Product-dependent | Full via backends | Full | Product closed; SDK subprocess local |
| PR automation | No | Full | No | Partial | Partial | Full cloud | Full product/plugins |
| Persistent memory | Partial | Full | No | Partial | Full | Closed | Full |
| User model | No | Partial | No | No | Full | Closed | Closed |
| Skill evolution | No | No | No | No | Full | No | Plugin/skill authoring, not autonomous |
| Scheduled automation | No | No | No | No | Full | Pattern only | Plugin/script possible |
| Messaging gateway | No | No | No | No | Full | No | GitHub/product integrations |
| Eval/tracing loop | Full eval metrics | Full tracing/review | Test/session sharing | Full usage/events | Full research/batch emphasis | Product closed | SDK usage/tests |
