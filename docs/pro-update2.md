# Product Hardening Merge

This is the merge contract for making tinyagent usable as a crisp local coding-agent product without growing a second harness beside the kernel.

The philosophy is `docs/MERGE.md`: add the smallest substrate change that makes the product real, collapse concepts aggressively, and delete old surface area instead of preserving it.

## Non-Negotiables

Use one public command:

```text
tinyagent
```

Use one durable user object:

```text
workspace -> conversation -> turn -> run
```

Use one product root:

```text
~/.tinyagent
```

Use one conversation store:

```text
conversation.json
turns.jsonl
```

Use one runtime API noun:

```text
/api/conversations
```

Do not keep old command names, storage aliases, duplicate route families, migration shims, or preservation branches. If a name is wrong, rename it once and update the tests.

## Vocabulary

```text
Workspace      registered target folder/repo
Conversation  user-visible thread inside a workspace
Turn           one user message and assistant response
Run            internal execution trace for a turn
Event          small recorded runtime fact
Artifact       large payload referenced by events
Profile        behavior/prompt/context/tool policy bundle
Provider       model backend
Config         user/project settings
```

Anything else needs a deletion or consolidation argument before it lands.

## Storage Contract

```text
~/.tinyagent/
  version.json
  config.toml
  workspaces/
    <workspace-id>/
      workspace.json
      conversations/
        <conversation-id>/
          conversation.json
          turns.jsonl
      runs/
        <run-id>/
          events.jsonl
          metrics.json
          final.md
          artifacts/
```

JSON files are the source of truth. SQLite can be added later as an index only after JSON scanning is a measured problem.

## Runtime Contract

The kernel still owns execution. Product state wraps it.

```text
ConversationStore.ensure(...)
RunController.start_conversation_turn(...)
Kernel.run(...)
ConversationStore.record_run_turn(...)
```

`tinyagent run` must create a conversation and record a turn. A run without a conversation is only acceptable for internal tests or direct `RunController.start_run(...)` use.

The HTTP API should expose:

```text
GET  /api/workspaces
POST /api/workspaces
GET  /api/runs
POST /api/runs
GET  /api/runs/<run-id>
GET  /api/runs/<run-id>/events
GET  /api/runs/<run-id>/events.json
POST /api/runs/<run-id>/cancel
POST /api/runs/<run-id>/approve

GET  /api/conversations
GET  /api/conversations/<conversation-id>/turns
POST /api/conversations/<conversation-id>/turns
```

Product UI requests carry `workspace_id`. `tinyagent serve` is product-scoped over `~/.tinyagent`, not pinned to one workspace. `POST /api/workspaces` registers a workspace path into the product home. `POST /api/runs` starts a raw run. `POST /api/conversations/<id>/turns` starts product conversation work.

## CLI Contract

```bash
tinyagent doctor
tinyagent config path
tinyagent init --workspace .
tinyagent workspaces list
tinyagent workspaces show <workspace-id>
tinyagent workspaces remove <workspace-id>
tinyagent run "..."
tinyagent conversations list
tinyagent conversations show <conversation-id>
tinyagent conversations archive <conversation-id>
tinyagent replay <run-id-or-path>
tinyagent inspect <run-id-or-path>
tinyagent serve
tinyagent eval <suite>
```

Path-based replay and inspect stay as debug primitives because traces are first-class evidence. They are not a second storage model.

`tinyagent serve --workspace <path>` may register an initial workspace, but the server world is the product home. The ChatUI can register a workspace path and jump among registered workspaces.

## Delete Budget

This merge should delete or collapse:

```text
old command package names
duplicate public console scripts
wrong storage/API vocabulary
conversation projection helpers over another noun
duplicate route branches for the same operation
append-only indexes that are not read
removed sandbox aliases
tests that hand-write product records instead of exercising behavior
```

If the diff adds a noun, route, or mode without removing a competing one, block it.

## Milestones

Application packaging lives outside `tinyagent.core`. `tinyagent.core` is the core harness and low-level runtime primitives. `tinyagent.app` owns product home state, registered workspaces, doctor checks, and the multi-workspace HTTP wrapper used by the ChatUI. `tinyagent.cli` is only the command surface.

### 1. Product Root

Implement:

```text
ProductHome
WorkspaceStore
tinyagent config path
tinyagent doctor
tinyagent init
tinyagent workspaces list/show/remove
```

Gate:

```text
tinyagent run "..." --workspace . --provider fake
```

writes under the registered workspace in `~/.tinyagent/workspaces/<id>/runs`.

### 2. Conversation Store

Implement:

```text
ConversationRecord
ConversationStore
conversation.json
turns.jsonl
prior_messages(...)
archive(...)
```

Gate:

```text
tinyagent run "hello" --workspace . --provider fake
tinyagent conversations list
tinyagent conversations show <conversation-id>
```

shows a real recorded turn. Tests must not create manual JSON fixtures for this.

### 3. Runtime API

Implement:

```text
RunController.start_conversation_turn(...)
GET /api/conversations
POST /api/conversations/<id>/turns
GET /api/conversations/<id>/turns
```

Gate:

```text
POST /api/conversations/<id>/turns
GET  /api/conversations/<id>/turns
```

records `turn.started` and `turn.completed`, then the second turn receives prior context.

### 4. App Projection

Implement:

```text
TinyagentClient
listWorkspaces()
registerWorkspace()
listConversations()
startConversationTurn()
active workspace_id state in the chat UI
conversation_id state in the chat UI
```

Gate:

The app uses a small UI SDK around `/api/workspaces`, `/api/conversations`, and `/api/runs`. Registering or selecting a workspace loads that workspace’s conversations, and a new message starts or continues a conversation in the selected workspace.

### 5. Crisp Policy Surface

Implement:

```text
workspace-mode = auto | worktree | current
sandbox-mode = none | container | native
```

Gate:

No removed aliases. Worktree behavior belongs to `workspace-mode`, not `sandbox-mode`.

## Review Checklist

Before submitting:

```text
rg "<old command>|<old store>|<old id>|<old route>"
rg "<old preservation language>|<old sandbox alias>"
uv run pytest
uv run ruff check <touched files>
npm run build  # when chatui changes
git diff --check
```

Expected result: no old vocabulary hits, tests green, and no whitespace errors.
