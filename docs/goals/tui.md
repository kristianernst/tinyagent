## Target decision

Throw out `chatui/`. Do not refactor it. TinyAgent should keep its Python runtime, event model, HTTP/SSE server, run store, approvals broker, and CLI, but the UI layer should be replaced with a new **OpenTUI client**.

The current UI surface is a React/Vite web app under `chatui/`, not a serious terminal UI. Its `package.json` is React + React DOM + Vite + TypeScript, and its useful parts are only the API/event-shaping code, not the UI implementation. 

The new shape should be:

```text
tinyagent/
  Python backend runtime, unchanged as much as possible

tui/
  Bun + OpenTUI frontend
  terminal rendering, composer, command palette, diff viewer, approvals, ASCII/animation

protocol/
  shared v1 event schema and fixtures
```

Use OpenTUI because it is the closest fit for a high-fidelity, efficient terminal UI. It is a native Zig terminal UI core with TypeScript bindings, powers OpenCode in production, and is currently Bun-first. ([OpenTUI][1])

## What TinyAgent already has

TinyAgent already has most of the backend needed for a premium agent TUI.

The CLI exposes `run`, `serve`, `replay`, `inspect`, conversations, workspaces, evals, skills, memory, and evolution commands. It also already supports live streaming through `--stream text` and `--stream jsonl`, with `JsonlStreamSink` as the cleanest machine-readable path.  

The runtime server is already the right abstraction boundary. `RunController` starts runs in background threads, stores runs, streams events through `RunBus`, persists public surface events through `SurfaceEventLogSink`, supports cancellation, and uses an `ApprovalBroker` for pending approval requests. That is exactly what a TUI client needs.  

The event envelope is already good: `id`, `seq`, `type`, `time`, `run_id`, `turn_id`, `item_id`, `visibility`, `durability`, `data`, and `artifact_refs`. The existing `chatui/src/lib/api.ts` mirrors that envelope and already implements SSE parsing. Keep that protocol idea; discard the UI. 

## Grok Build feedback to copy

The reliable public material I found is mostly xAI’s own docs plus xAI-curated launch feedback, so I would treat it as product signal, not a neutral user survey. Still, the signal is useful.

Grok Build’s product shape is clear: interactive TUI, headless scripting, and ACP integration are all first-class modes. Its docs describe the TUI as rich, mouse-interactive, and fullscreen, while also supporting headless commands and streaming JSON output. ([xAI Docs][2]) ([xAI Docs][3])

The most important lesson is not “copy Grok’s model.” It is **copy the interaction loop**: plan first, execute in phases, keep context visible, expose `/context`, `/model`, `/compact`, `/plan`, `/rewind`, `/usage`, `/btw`, `/sessions`, and make approval mode easy to toggle. Grok’s docs explicitly define plan mode as blocking write tools except the session plan file, and its command palette groups session, context, model, and tool actions. ([xAI Docs][4])

The positive feedback around Grok Code Fast emphasized perceived speed, small focused tasks, rapid iteration, and plan-then-execute workflows. xAI’s own launch page quotes a user saying the speed changed how they worked in Cursor, and the longer feedback specifically says smaller focused tasks plus phased execution worked better than dumping one huge prompt. ([xAI][5])

One caution: do not hardcode `grok-code-fast-1`. xAI’s current docs say several older model slugs, including `grok-code-fast-1`, were retired on May 15, 2026, and deprecated text slugs redirect to `grok-4.3`. Build TinyAgent around provider/model configurability, not a fixed Grok SKU. ([xAI Docs][6])

## Implementation plan

### Phase 0: delete the existing UI

Remove or archive:

```text
chatui/
```

Do not incrementally port the React components. The current `components.tsx` has useful conceptual patterns — collapsible tool pills, reasoning sections, answer streaming, diff preview, and mode switch — but the actual browser React implementation should not survive. 

Keep only these ideas:

```text
RunEvent type
SSE parser
event reducer behavior
approval handling
artifact link model
workspace/conversation/run API shape
```

Create:

```text
docs/tui-contract.md
docs/tui-implementation-plan.md
tui/
```

### Phase 1: consolidate the protocol around `/v1`

Prefer `/v1` for the new TUI. TinyAgent already has `runtime/protocol_v1.py` with `SCHEMA_VERSION = 1`, run-start keys, normalized run objects, health, workspaces, runs, SSE events, event JSON, artifacts, approvals, and cancellation. 

Add these missing or currently legacy-only endpoints:

```text
GET  /v1/workspaces/{workspace_id}/files
GET  /v1/workspaces/{workspace_id}/git/status
GET  /v1/conversations?workspace_id=...
GET  /v1/conversations/{conversation_id}/turns?workspace_id=...
POST /v1/runs/{run_id}/fork
GET  /v1/runs/{run_id}/approvals
```

Current `app/server.py` already has legacy `/api/workspace/files`, `/api/git/status`, `/api/conversations`, run events, approvals, cancellation, and artifacts. Move or mirror those into `/v1` instead of making the TUI depend on mixed protocol versions.  

Also add a schema export command:

```bash
uv run python scripts/export_surface_schema.py > tui/src/protocol/schema.generated.json
```

The TypeScript side should have generated or checked types for:

```text
RunEvent
RunObject
Workspace
Conversation
Approval
Artifact
GitSnapshot
StartRunRequest
StartRunResponse
```

### Phase 2: build the new OpenTUI package

Create:

```text
tui/
  package.json
  bun.lock
  src/main.ts
  src/app.tsx
  src/backend/spawn.ts
  src/backend/client.ts
  src/backend/sse.ts
  src/protocol/events.ts
  src/state/reducer.ts
  src/state/store.ts
  src/components/Transcript.tsx
  src/components/Composer.tsx
  src/components/StatusBar.tsx
  src/components/ToolTimeline.tsx
  src/components/DiffViewer.tsx
  src/components/ApprovalModal.tsx
  src/components/CommandPalette.tsx
  src/components/Ascii.tsx
  src/components/DebugOverlay.tsx
  src/keymap.ts
  src/theme.ts
  src/commands.ts
  fixtures/
```

Use Bun + OpenTUI. OpenTUI currently documents Bun as the supported runtime, with Node and Deno support in progress. ([OpenTUI][1])

Default renderer config:

```ts
createCliRenderer({
  screenMode: "split-footer",
  footerHeight: 12,
  exitOnCtrlC: false,
  targetFps: 30,
  maxFps: 60,
  useMouse: true,
  consoleMode: "disabled",
})
```

Use `split-footer` as the default because it lets the transcript remain in normal terminal scrollback while the composer/status area stays pinned at the bottom. OpenTUI specifically documents split-footer as a reserved footer region with normal output above it, plus scrollback writers for styled markdown, code, and streaming output. ([OpenTUI][7])

Add an alternate full-screen mode:

```text
/mode fullscreen
/mode footer
```

OpenTUI’s alternate-screen mode is still useful for session browser, diff review, and dashboard views. ([OpenTUI][7])

### Phase 3: launch/connect backend from the TUI

Implement two modes.

First, connect mode:

```bash
tinyagent-tui --server http://127.0.0.1:8765
```

Second, spawn mode:

```bash
tinyagent-tui --workspace . --provider fake
```

Spawn mode should run:

```bash
python -m tinyagent serve \
  --workspace . \
  --host 127.0.0.1 \
  --port 0 \
  --provider <provider> \
  --stream \
  --debug 1
```

`serve --port 0` should work with `ThreadingHTTPServer`; the CLI already prints `server.server_port`, so the TUI can parse the selected port from stderr/stdout or, better, add a machine-readable `--print-json` flag.

Add to `tinyagent/cli.py`:

```text
tinyagent tui
```

But keep it as a thin launcher. Do not add OpenTUI/Bun dependencies to Python `pyproject.toml`. The current Python project has no runtime dependencies, and that is worth preserving. 

### Phase 4: port the event reducer, not the UI

Move the logic from `chatui/src/lib/useRun.ts` into a pure reducer:

```ts
export function reduceEvent(state: AppState, event: RunEvent): AppState
```

State model:

```ts
type AppState = {
  workspaces: Workspace[]
  activeWorkspaceId: string | null
  sessions: SessionSummary[]
  activeSession: SessionState | null
  phase: "idle" | "thinking" | "streaming" | "approval" | "failed"
  approvalMode: "ask" | "always" | "plan"
  ui: UiState
}

type SessionState = {
  conversationId: string
  runId: string | null
  turns: TurnState[]
  pendingApproval: Approval | null
  artifacts: Artifact[]
  git: GitSnapshot | null
  lastSeq: number
  eventsBySeq: Map<number, RunEvent>
}

type TurnState = {
  id: string
  user: string
  assistant: string
  reasoning: ReasoningBlock[]
  tools: ToolCallView[]
  phase: "thinking" | "streaming" | "done" | "failed" | "cancelled"
}
```

Handle at least these events:

```text
run.started
turn.started
model.call.started
model.reasoning.delta
model.reasoning.completed
model.text.delta
model.message.completed
model.tool_call.assembly.completed
tool.execution.started
tool.execution.output.delta
tool.execution.output.snapshot
tool.execution.completed
tool.execution.failed
tool.execution.blocked
tool.execution.cancelled
approval.requested
approval.resolved
approval.expired
artifact.created
artifact.materialized
workspace.mutation.detected
patch.applied
file.edited
diff.finalized
model.usage
run.completed
run.failed
run.cancelled
```

The current React hook already handles most of this mapping. The missing high-value additions are `tool.execution.output.delta`, `model.usage`, `patch.applied`, `file.edited`, and `diff.finalized`.  

### Phase 5: render the core TUI

Build the initial screen as four surfaces:

```text
┌──────────────── transcript / scrollback ────────────────┐
│ streamed markdown, reasoning folds, tool summaries        │
│ code blocks, shell output, final answer                   │
└───────────────────────────────────────────────────────────┘
┌ tool/context rail ┐ optional, toggle with Ctrl+R
│ running tool      │
│ git dirty state   │
│ artifacts         │
│ token usage       │
└───────────────────┘
┌ composer ────────────────────────────────────────────────┐
│ > prompt, @file, /command, !shell                         │
└ status: model | cwd | branch | mode | tokens | spinner ───┘
```

Use OpenTUI’s `Markdown` component for streamed assistant output; it supports syntax-aware markdown and streaming updates. ([OpenTUI][8])

Use OpenTUI’s `Code` component for code blocks; it uses Tree-sitter for syntax highlighting. ([OpenTUI][9])

Use OpenTUI’s `Diff` component for patch review; it supports unified and split diffs, syntax highlighting, optional line numbers, and split-view scroll sync. ([OpenTUI][10])

Use OpenTUI’s `ASCIIFont` component for the TinyAgent identity, mode banners, and high-fidelity terminal headers. It has multiple ASCII art font styles including tiny, block, shade, slick, huge, grid, and pallet. ([OpenTUI][11])

### Phase 6: implement Grok-inspired commands

Implement these first because they materially affect UX:

```text
/new
/sessions
/resume
/fork
/rewind
/context
/model
/plan
/always-approve
/ask
/compact
/compact-mode
/usage
/theme
/stop
/help
```

Map them to TinyAgent backend concepts:

```text
/new              create new conversation_id
/sessions         list conversations
/resume           load conversation turns and replay last run events
/fork             call run fork endpoint
/rewind           pick event seq, fork from that seq
/context          show context summary and context artifacts
/model            switch provider/model for next run
/plan             run with write tools blocked except plan file
/always-approve   approval_mode = yolo
/ask              approval_mode = on-request
/compact          backend conversation compaction task
/usage            aggregate model.usage events
/stop             POST cancel
```

The most important one is `/plan`. Grok Build’s plan mode blocks write tools except the session plan file and keeps the plan visible. TinyAgent should implement the same behavior as a backend policy/profile mode, not just as a frontend label. ([xAI Docs][4])

Add a Python-side policy mode:

```python
ApprovalMode = Literal["never", "on-request", "yolo"]
SessionMode = Literal["normal", "plan"]
```

Then implement:

```text
normal: existing behavior
plan: shell/search/read allowed, apply_patch/file mutation blocked, plan artifact allowed
```

The UI should show plan mode in the status bar and keep the current plan pinned in the context rail.

### Phase 7: add approval and diff flows

Approval modal:

```text
Tool: shell
Command: pytest tests/foo.py
Risk: modifies nothing / reads workspace / writes files / network / unknown

[A] approve once
[R] approve for run
[D] deny
[E] explain risk
```

Backend mapping:

```text
POST /v1/runs/{run_id}/approvals/{approval_id}/resolve
```

TinyAgent already has the approval broker and server-side resolve path; the TUI should not use the blocking `_CliApprovalHandler`.  

Diff flow:

```text
1. show patch preview when apply_patch assembles or completes
2. render unified by default
3. toggle split view
4. keyboard jump between hunks
5. show changed file list
6. show git dirty state after run completion
```

Use the existing `git_status_response` logic as the backend source for branch, dirty files, and diff until a cleaner v1 schema is added. 

### Phase 8: high-fidelity terminal polish

Spinner states should be meaningful, not decorative:

```text
idle
thinking
planning
reading
searching
running_shell
editing
waiting_approval
streaming
compacting
cancelled
failed
done
```

Use fixed-width spinner frames. Avoid mixed-width emoji in the status bar unless normalized. Provide selectable spinner packs:

```text
ascii
braille
dots
scanline
kaomoji-safe
minimal
```

Use ASCII art for:

```text
startup identity
plan mode header
approval warning
run completed
run failed
compact mode banner
debug overlay title
```

Use OpenTUI live rendering only while animations are visible. The renderer supports target FPS, max FPS, live render requests, pausing, suspending, resize events, terminal capabilities, and a debug overlay mechanism. ([OpenTUI][7])

### Phase 9: add headless and ACP parity

TinyAgent already has `--stream jsonl`. Keep improving that.

Target CLI parity:

```bash
tinyagent run "explain this repo" --stream jsonl
tinyagent run "fix failing tests" --output-format json
tinyagent agent stdio
```

Grok Build’s headless mode supports plain, JSON, and streaming JSON output, and its ACP mode runs over JSON-RPC on stdin/stdout. TinyAgent should converge on the same shape because it lets one backend power the TUI, scripts, bots, and editor clients. ([xAI Docs][3])

Add later:

```text
tinyagent agent stdio
```

Protocol:

```text
stdin/stdout: JSON-RPC
stderr: logs only
events: session/update
requests: session/prompt, session/cancel, approval/resolve
```

Do not start here. Start with existing HTTP/SSE because TinyAgent already has it.

## Specific PR breakdown

PR 1: delete/archive `chatui`, add `docs/tui-contract.md`, and add `/v1` protocol tests.

PR 2: add missing `/v1` endpoints for workspace files, git status, conversations, run fork, and pending approvals.

PR 3: create `tui/` OpenTUI skeleton with backend connect/spawn, health check, workspace picker, composer, and status bar.

PR 4: implement SSE client and pure event reducer. Use recorded fake-provider event fixtures.

PR 5: render transcript, streamed markdown, reasoning folds, tool timeline, and final answer.

PR 6: implement approvals, cancellation, artifacts, and diff viewer.

PR 7: implement command palette: `/plan`, `/context`, `/model`, `/sessions`, `/rewind`, `/usage`, `/compact-mode`, `/theme`.

PR 8: add ASCII art, spinner packs, split-footer scrollback, debug overlay, keyboard/mouse polish, and perf tests.

PR 9: add `tinyagent agent stdio` and ACP-compatible adapter.

## Acceptance criteria

The new TUI is acceptable only if these pass:

```text
uv run pytest
uv run ruff check .
bun test
bun run build
```

Functional acceptance:

```text
tinyagent-tui --workspace . --provider fake
```

must support:

```text
start run
stream assistant output
show tool calls
show shell output
cancel run
approve/deny tool call
render patch diff
show git dirty state
resume conversation
replay previous run
switch approval mode
run /plan without file writes
```

Performance acceptance:

```text
10,000 events replay without freezing
large run transcript remains scrollable
200k-character diff is truncated intentionally, not accidentally
streaming token update appears within one render frame locally
terminal resize does not corrupt layout
Ctrl+C/Esc exits or cancels cleanly
```

## Main engineering rule

Do not rebuild the agent. Do not rebuild the server. Do not salvage the React UI.

Keep:

```text
Kernel
RunController
RunBus
SurfaceEventLogSink
ApprovalBroker
RunStore
ConversationStore
/v1 protocol
```

Replace:

```text
chatui/
browser React components
web CSS animation system
ad hoc frontend state hook
```

The highest-leverage implementation is a new OpenTUI frontend over TinyAgent’s existing evented runtime.

[1]: https://opentui.com/docs/getting-started/ "Getting started"
[2]: https://docs.x.ai/build/overview "Getting Started | xAI Docs"
[3]: https://docs.x.ai/build/cli/headless-scripting "Headless & Scripting | xAI Docs"
[4]: https://docs.x.ai/build/modes-and-commands "Modes and Commands | xAI Docs"
[5]: https://x.ai/news/grok-code-fast-1 "Grok Code Fast 1 | xAI"
[6]: https://docs.x.ai/docs/models "Models | xAI Docs"
[7]: https://opentui.com/docs/core-concepts/renderer "Renderer"
[8]: https://opentui.com/docs/components/markdown "Markdown"
[9]: https://opentui.com/docs/components/code "Code"
[10]: https://opentui.com/docs/components/diff "Diff"
[11]: https://opentui.com/docs/components/ascii-font "ASCIIFont"
Design-system visual: [open the generated design preview](sandbox:/mnt/data/a_high_detail_infographic_design_document_screen.png).

I agree with the correction. The target should not be “replace the old TUI with a nicer TUI.” The target should be a **terminal-native agent cockpit**: a high-performance command center for planning, execution, context, replay, approvals, diffs, evals, and model control.

TinyAgent already has the hard backend pieces: event envelopes, run lifecycle, streaming, approvals, workspaces, conversations, artifacts, and a v1-ish protocol. The current web UI is not the foundation. The `chatui` package is a React/Vite browser app, while the backend already has a proper `RunEvent` shape and SSE client behavior that can be ported into a pure reducer.  

## New ambition

The new product direction:

**TinyAgent TUI becomes the “terminal OS” for agentic coding.**

It should not feel like a chat app. It should feel like a hybrid of:

Cursor CLI’s command affordances, OpenCode’s terminal-native polish, Codex CLI’s seriousness around event handling, Grok Build’s speed/control loop, and a custom visual identity that makes TinyAgent feel like its own product.

The backend remains Python. The frontend becomes OpenTUI. The old UI is deleted.

## What Grok-style feedback implies

The durable lesson from Grok Code Fast / Grok Build-style reception is not just “make it fast.” It is that users seem to respond to **low-latency iteration, plan-first execution, clear context, controllable autonomy, and headless/scriptable parity**. Public material around Grok Code Fast describes it as a fast, economical coding model launched across coding-agent surfaces including Cursor, Copilot, opencode, Cline, Roo Code, Kilo Code, and Windsurf, which is useful market evidence that speed plus agent integration matters. ([Wikipedia][1])

There is also a harder research-backed reason to design for control: real-world coding-agent sessions show frequent human correction and interruption, with SWE-chat reporting user pushback through corrections, failure reports, or interruptions in 44% of turns. ([arXiv][2]) Raw execution traces are also difficult for developers to interpret; recent work on coding-agent failure explanations argues for structured, visual, actionable traces rather than dumping raw logs. ([arXiv][3])

So the product thesis is:

**A great coding-agent TUI is not a pretty transcript. It is a control surface for interrupting, steering, inspecting, replaying, and recovering agent work.**

## Design stack

The design stack should be treated as seriously as the technical stack.

### 1. Product design layer

Core product promise:

```text
TinyAgent helps a developer supervise powerful coding agents without losing control.
```

Primary user states:

```text
thinking
planning
searching
reading
editing
running shell
waiting for approval
reviewing diff
compacting context
evaluating
replaying
failed
recovered
```

Primary product modes:

```text
Chat mode       normal prompt → run loop
Plan mode       agent may inspect, but write operations are locked
Build mode      agent executes implementation steps
Review mode     diff, tool calls, tests, and risks become central
Replay mode     inspect past runs event-by-event
Model lab       compare providers/models on the same task
Eval lab        run local benchmark/eval suites from inside the TUI
Skill forge     turn successful runs into reusable skills
```

TinyAgent already exposes evals, skills, memory, evolution, run replay, run inspection, workspaces, and conversations through the CLI. Those should become first-class surfaces in the TUI, not hidden commands.  

### 2. Interaction design layer

The core interaction model should be:

```text
Plan → Inspect → Approve → Execute → Review → Commit / Rewind / Fork
```

The TUI should always show the user:

```text
What is the agent doing?
Why is it doing it?
What context is it using?
What files can it mutate?
What has changed?
What can I interrupt, approve, rewind, or fork?
```

The command language should be dense and memorable:

```text
/new              new session
/sessions         session browser
/resume           resume prior session
/plan             enter plan-only mode
/build            leave plan mode and execute
/context          context graph
/model            model/provider switcher
/usage            token/cost analytics
/diff             diff forge
/review           review current run
/rewind           rewind to event
/fork             fork from event
/eval             eval lab
/skills           skill forge
/compact          compact conversation
/memory           memory surface
/theme            theme switcher
/debug            performance/event overlay
/headless         show equivalent headless command
/acp              ACP bridge status
/help             command map
```

The keybinding model should be terminal-native:

```text
Enter             send / confirm
Esc               close modal / cancel palette
Ctrl+C            interrupt run, second Ctrl+C exits
Ctrl+K            command palette
Ctrl+R            right rail on/off
Ctrl+P            plan panel
Ctrl+D            diff forge
Ctrl+U            usage panel
Tab               next focus region
Shift+Tab         previous focus region
?                 contextual help
```

### 3. Visual design layer

Visual direction:

```text
dark terminal
high contrast
low-noise neon accents
ASCII-first identity
cybernetic but not childish
dense but legible
designed for long sessions
```

Color tokens:

```ts
export const color = {
  bg: "#0b0f14",
  surface: "#11161c",
  surface2: "#161c23",
  border: "#22303a",
  borderFocus: "#58a6ff",

  text: "#e6edf3",
  muted: "#8b949e",
  subtle: "#6e7681",

  blue: "#58a6ff",
  cyan: "#56d6a4",
  green: "#2ea043",
  yellow: "#e3b341",
  orange: "#f0883e",
  red: "#f85149",
  pink: "#ff6b9a",
  purple: "#a371f7",
};
```

Semantic tokens:

```ts
export const semantic = {
  thinking: color.yellow,
  planning: color.purple,
  reading: color.blue,
  searching: color.cyan,
  editing: color.orange,
  success: color.green,
  danger: color.red,
  approval: color.orange,
  muted: color.muted,
};
```

Typography:

```text
Primary: JetBrains Mono
Fallbacks: Berkeley Mono, IBM Plex Mono, Menlo, Consolas, monospace
Minimum terminal target: 100×30
Ideal target: 140×40+
```

Border language:

```text
single-line border        normal panels
double-line border        primary modal
dotted ASCII border       plan mode / preview
red dashed border         approval or danger
green dashed border       success / completed run
no border                 transcript body
```

ASCII identity:

```text
Startup logo
Plan mode banner
Approval warning banner
Run complete badge
Failure badge
Model lab header
Eval lab header
```

Spinner packs:

```text
ascii       - \ | /
dots        . .. ... ....
braille     ⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏
scanline    ░▒▓█▓▒░
orbit       ◜ ◠ ◝ ◞ ◡ ◟
minimal     · · ·
```

Rule: the status bar uses fixed-width spinner frames only. No width-jitter from emoji.

### 4. Component design layer

The TUI should have these core components:

```text
Root Shell
  owns renderer, split-footer/fullscreen mode, resize, mouse, keymap

Transcript
  streaming markdown, final answers, code blocks, folded reasoning

Composer
  multiline prompt, history, @file autocomplete, !shell, /commands

Command Palette
  fuzzy command search, keyboard-first, context-aware actions

Session Rail
  sessions, branches, forks, active run state

Context Graph
  files, symbols, memory, MCP resources, loaded skills, selected context

Tool Timeline
  shell, search, read, apply_patch, MCP, LSP, evals, auto-review

Approval Gate
  risk, command, file targets, approve once/run, deny, explain

Diff Forge
  split/unified diff, hunk nav, file nav, approve/reject, git status

Plan Board
  current plan, step states, blocker list, allowed/disallowed actions

Usage Panel
  tokens, model calls, latency, cost, compression, context budget

Replay Cinema
  event timeline, scrubber, fork from event, compare branches

Model Lab
  provider switcher, A/B run comparison, latency/quality notes

Eval Lab
  run suite, compare variants, show failures, open artifacts

Skill Forge
  draft skill from run, inspect, eval, install/reject

Debug Overlay
  FPS, render time, event queue, SSE latency, reducer time, memory
```

### 5. Technical design stack

Recommended stack:

```text
Frontend runtime:
  Bun

TUI engine:
  OpenTUI

Language:
  TypeScript

State:
  pure event reducer + append-only event log

Runtime validation:
  zod or generated JSON schema validators

Backend:
  existing TinyAgent Python runtime

Transport v1:
  HTTP + SSE

Transport v2:
  JSON-RPC over stdio

Interoperability:
  ACP adapter after the TUI stabilizes

Testing:
  bun test
  golden event fixtures
  terminal snapshot tests
  replay stress tests
  Python pytest for protocol endpoints

Performance:
  event coalescing
  transcript windowing
  virtualized tool output
  diff truncation with explicit expansion
  render budget instrumentation
```

JSON-RPC is a good later transport because it is transport-independent, supports notifications, and can be carried over file-descriptor I/O, HTTP, TCP, and similar transports. ([Wikipedia][4]) For TinyAgent, HTTP/SSE should remain the first implementation path because the runtime server already supports event streaming, run storage, approvals, and cancellation.  

### 6. Protocol design layer

Do not let UI state become ad hoc. The TUI is a projection of the event log.

TinyAgent already has durable and live-only event types, visibility levels, debug levels, event durability, JSON-safe event serialization, `JsonlStreamSink`, `ConsoleTextSink`, and a structured event envelope.  

The frontend should have one canonical reducer:

```ts
function reduceEvent(state: AppState, event: RunEvent): AppState
```

No component should directly interpret raw events except through selectors.

Core event projections:

```text
RunEvent[] → Transcript
RunEvent[] → ToolTimeline
RunEvent[] → ApprovalState
RunEvent[] → DiffState
RunEvent[] → UsageStats
RunEvent[] → ReplayTimeline
RunEvent[] → FailureExplanation
RunEvent[] → SessionSummary
```

The protocol should grow toward:

```text
/v1/health
/v1/workspaces
/v1/workspaces/{id}/files
/v1/workspaces/{id}/git/status
/v1/conversations
/v1/conversations/{id}/turns
/v1/runs
/v1/runs/{id}
 /events
 /events.jsonl
 /artifacts
 /approvals
 /cancel
 /fork
```

TinyAgent already has `SCHEMA_VERSION = 1`, v1 helpers, health responses, normalized run objects, links, and OpenAPI response helpers. That should become the public contract for the TUI. 

## Repository shape

Replace this:

```text
chatui/
```

With this:

```text
tui/
  package.json
  bun.lock
  src/
    main.ts
    app.tsx

    backend/
      connect.ts
      spawn.ts
      client.ts
      sse.ts

    protocol/
      event.ts
      schema.ts
      commands.ts

    state/
      reducer.ts
      selectors.ts
      store.ts
      fixtures.ts

    design/
      tokens.ts
      theme.ts
      borders.ts
      spinners.ts
      ascii.ts

    components/
      RootShell.tsx
      Transcript.tsx
      Composer.tsx
      CommandPalette.tsx
      StatusBar.tsx
      SessionRail.tsx
      ContextGraph.tsx
      ToolTimeline.tsx
      ApprovalGate.tsx
      DiffForge.tsx
      PlanBoard.tsx
      UsagePanel.tsx
      ReplayCinema.tsx
      ModelLab.tsx
      EvalLab.tsx
      SkillForge.tsx
      DebugOverlay.tsx

    keymap.ts
    routes.ts
    perf.ts

  fixtures/
    fake-run-basic.jsonl
    fake-run-tools.jsonl
    fake-run-approval.jsonl
    fake-run-diff.jsonl
    fake-run-failure.jsonl
    fake-run-10k-events.jsonl

  tests/
    reducer.test.ts
    sse.test.ts
    keymap.test.ts
    replay.test.ts
    perf.test.ts
```

Python additions:

```text
tinyagent/runtime/protocol_v1.py      expand public protocol
tinyagent/app/server.py               add missing v1 endpoints
tinyagent/cli.py                      add tinyagent tui launcher
scripts/export_surface_schema.py      generate TS schema
tests/test_protocol_v1.py             endpoint contract tests
tests/test_surface_events.py          event visibility tests
```

## Five-month project

Assumption: start Monday, May 18, 2026. End Friday, October 16, 2026. This is a 5-month product build, not a weekend refactor.

### Month 1: foundation and hard reset

**May 18 – June 12, 2026**

Goal: remove the old UI, lock the protocol, and get a functional terminal shell connected to the backend.

Deliverables:

```text
chatui/ removed or archived
tui/ package created
OpenTUI renderer booting
backend connect/spawn mode
/v1 protocol normalized
event fixtures generated
pure reducer implemented
workspace picker
basic transcript
basic composer
basic status bar
```

Week 1:

```text
Delete/archive chatui
Create tui package
Add design tokens and theme skeleton
Write docs/tui-contract.md
Write docs/tui-design-system.md
Export event fixtures from fake provider
```

Week 2:

```text
Normalize /v1 endpoints
Add /v1/workspaces/{id}/files
Add /v1/workspaces/{id}/git/status
Add /v1/conversations
Add /v1/runs/{id}/approvals
Add Python protocol tests
```

Week 3:

```text
Implement TUI backend client
Implement SSE parser
Implement spawn/connect modes
Render root shell
Render split-footer layout
Implement status bar
```

Week 4:

```text
Port event interpretation into pure reducer
Replay fixtures into TUI
Render transcript
Render assistant streaming
Render run completed/failed/cancelled states
```

Exit criteria:

```text
tinyagent-tui --workspace . --provider fake works
A fake run streams into the terminal
10k fixture events replay without state corruption
No React/Vite browser UI remains as product surface
```

### Month 2: core agent experience

**June 15 – July 10, 2026**

Goal: make it useful as a real coding-agent TUI.

Deliverables:

```text
command palette
multiline composer
@file picker
!shell entry
tool timeline
approval gate
streamed markdown/code blocks
basic diff preview
cancel/interruption
session browser v1
```

Week 5:

```text
Composer multiline editing
Prompt history
Slash command detection
Command palette
/help surface
```

Week 6:

```text
@file autocomplete using workspace files endpoint
!shell command affordance
Keyboard focus system
Mouse optional interactions
```

Week 7:

```text
Tool timeline
Tool output folding
Shell output streaming
Search/read/apply_patch summaries
Artifact list
```

Week 8:

```text
Approval gate
Approve once
Approve for run
Deny
Cancel while waiting approval
Approval risk display
```

Exit criteria:

```text
Can run a real task
Can inspect tool calls
Can approve/deny actions
Can cancel cleanly
Can resume a prior session
```

### Month 3: power features and product identity

**July 13 – August 14, 2026**

Goal: make the TUI feel like a differentiated product.

Deliverables:

```text
Plan mode
Plan board
Diff forge
Context graph
Usage panel
ASCII identity system
spinner packs
theme system
model/provider switcher
```

Week 9:

```text
Backend plan mode
Block apply_patch/write tools in plan mode
Allow read/search/shell inspection under policy
Persist plan artifact
Show plan mode banner
```

Week 10:

```text
Plan board UI
Step state tracking
Plan update events
Build-from-plan transition
```

Week 11:

```text
Diff forge
Unified/split diff view
Hunk navigation
Changed file list
Git dirty state
Diff truncation with explicit expansion
```

Week 12:

```text
Context graph
Loaded files
Memory
Skills
MCP resources
LSP status
Context budget
```

Week 13:

```text
Usage panel
Token/cost/latency view
Model call timeline
Provider/model switcher
ASCII logo/banners
Spinner packs
Theme switcher
```

Exit criteria:

```text
/plan is a real backend mode, not a UI label
Diff review is better than raw terminal output
Context is visible and inspectable
TUI has a recognizable TinyAgent visual identity
```

### Month 4: replay, evals, and advanced control

**August 17 – September 11, 2026**

Goal: turn TinyAgent into a serious harness, not just a chat loop.

Deliverables:

```text
Replay cinema
Rewind/fork
Eval lab
Skill forge
failure explanation view
model comparison
performance instrumentation
```

Week 14:

```text
Replay cinema
Event scrubber
Jump to event
View raw event
View projected UI state at event
```

Week 15:

```text
/fork from run
/rewind to event
Branch/session comparison
Run graph display
```

Week 16:

```text
Eval lab
Run eval suite from TUI
Show pass/fail table
Open artifacts
Compare variants
```

Week 17:

```text
Skill forge
Draft skill from run
Inspect draft
Eval draft
Install/reject draft
```

Week 18:

```text
Failure explanation panel
Classify failure source
Show last successful event
Show failed tool/model call
Suggest recovery actions
```

Exit criteria:

```text
A run can be replayed, forked, and inspected
Eval results are visible inside the TUI
A successful run can become a candidate skill
Failures are explainable without reading raw JSONL
```

### Month 5: ecosystem, packaging, and release

**September 14 – October 16, 2026**

Goal: ship a robust public v1.

Deliverables:

```text
headless parity
JSONL streaming polish
JSON-RPC stdio prototype
ACP adapter prototype
installer/package story
terminal compatibility matrix
docs
beta feedback loop
v1 release
```

Week 19:

```text
Headless parity audit
Every major TUI action has CLI/headless equivalent
/output-format json
/usage emits machine-readable data
```

Week 20:

```text
JSON-RPC stdio prototype
stdin/stdout protocol
stderr logs only
session.start
session.prompt
session.cancel
approval.resolve
event notification stream
```

Week 21:

```text
ACP adapter prototype
Map TinyAgent sessions to ACP sessions
Map event stream to client updates
Map approvals/cancel/fork where possible
```

Week 22:

```text
Packaging
tinyagent tui launcher
Install docs
Terminal compatibility test:
  iTerm2
  WezTerm
  kitty
  Apple Terminal
  VS Code terminal
  Windows Terminal
  tmux
  SSH
```

Week 23:

```text
Beta hardening
Perf tuning
Snapshot tests
Crash recovery
Docs
Release notes
v1.0 cut
```

Exit criteria:

```text
One-command TUI launch works
Headless mode remains first-class
ACP prototype works enough to validate direction
Terminal compatibility is documented
v1.0 release is usable by external users
```

## Project epics

Use these as GitHub milestones or project columns.

```text
E1  TUI hard reset
E2  v1 protocol contract
E3  OpenTUI shell
E4  Event reducer and fixtures
E5  Composer and command palette
E6  Tool timeline
E7  Approval gate
E8  Plan mode
E9  Diff forge
E10 Context graph
E11 Replay and fork
E12 Eval lab
E13 Skill forge
E14 Usage/model lab
E15 Headless and JSON-RPC
E16 ACP adapter
E17 Packaging and release
```

## Success metrics

Performance:

```text
<100 ms local event-to-render latency
30 FPS stable target
60 FPS max for animations only
10k events replay without UI lockup
200k-character diff handled without accidental full render
No terminal corruption on resize
No width jitter in status bar
```

Product:

```text
New user can start a run in <60 seconds
User can understand current agent action at all times
User can interrupt any active run
User can approve or deny risky actions without leaving TUI
User can review all file mutations before committing
User can replay/fork a previous run
User can run evals from the same interface
```

Engineering:

```text
All TUI state is derived from events
All backend protocol behavior is tested
No frontend component directly mutates backend state without command layer
No stdout logging contaminates machine-readable protocol output
Fixtures cover success, failure, approval, cancellation, large diff, and long run
```

## Non-negotiables

Do not keep `chatui`.

Do not build “chat first.”

Do not make plan mode cosmetic.

Do not let the TUI depend on hidden Python globals.

Do not mix logs and protocol output.

Do not make mouse required.

Do not let diff review be a raw pre block.

Do not ship without replay.

Do not ship without cancellation.

## Concrete first PR

The first PR should be boring and aggressive:

```text
Title:
  Replace browser chat UI with terminal TUI foundation

Changes:
  - Remove/archive chatui/
  - Add tui/ package skeleton
  - Add design tokens
  - Add event fixtures
  - Add docs/tui-contract.md
  - Add docs/tui-design-system.md
  - Add /v1 protocol test coverage
  - Add tinyagent tui launcher stub

Definition of done:
  - uv run pytest passes
  - uv run ruff check . passes
  - bun test passes
  - bun run build passes
  - tinyagent-tui opens a terminal shell and connects to /v1/health
```

The larger point: TinyAgent already has enough backend architecture to support a serious product. The missing piece is not “a UI.” It is a designed terminal control system with a strict event contract, strong visual identity, and power-user workflows.

[1]: https://en.wikipedia.org/wiki/Grok_%28chatbot%29?utm_source=chatgpt.com "Grok (chatbot)"
[2]: https://arxiv.org/abs/2604.20779?utm_source=chatgpt.com "SWE-chat: Coding Agent Interactions From Real Users in the Wild"
[3]: https://arxiv.org/abs/2603.05941?utm_source=chatgpt.com "XAI for Coding Agent Failures: Transforming Raw Execution Traces into Actionable Insights"
[4]: https://en.wikipedia.org/wiki/JSON-RPC?utm_source=chatgpt.com "JSON-RPC"
