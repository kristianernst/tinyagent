The earlier recommendation is directionally right, but it risks turning the chat UI into a product architecture before the core runtime is solid. I would keep the design centered on a much narrower principle:

Tinyagent should expose one high-quality agent execution substrate. CLI, SDK, TUI, web UI, evals, IDEs, and future orchestrators should all be thin projections over that substrate.

The chat UI is useful because it forces the substrate to prove five things: real streaming, stable event semantics, approval/cancel control, artifact retrieval, and resumable conversation state. It should not become a second path through the agent.

## 1. The core philosophy I would preserve

Tinyagent’s strongest architectural shape right now is that a run is small, replayable, inspectable, and local. The current project shape matches that: `agentd` owns `Kernel`, `RunState`, `Profile`, `Tool`, `PolicyEngine`, `Transcript`, `Event`, workspace handling, and model providers, while `agentctl` is just a frontend and `chatui` is a newly added consumer over HTTP/SSE. The design note in the branch explicitly says not to optimize for chat UI specifically; CLIs, evals, IDE plugins, and external orchestrators should consume the same surface.

That means the core should remain:

Small. No heavy web framework or frontend-shaped abstractions in `agentd`.

Auditable. Every meaningful decision should be reconstructable from events, transcript, artifacts, and workspace diffs.

Coding-first. The runtime should optimize for long-running code tasks, workspace mutation, approvals, tool identity, diffs, and recovery — not just conversational niceness.

Surface-agnostic. A browser, CLI, TUI, SDK, or IDE should consume the same events, not ask the kernel for different output shapes.

Append-only where possible. Runs and sessions should be observable timelines. Mutation should happen in the workspace, not in hidden UI state.

The question is not “how do we add chat?” The question is “what must the runtime expose so any interface can drive the agent without knowing kernel internals?”

## 2. What the current branch shows

The `feature/chatui` branch is intentionally light. It adds `chatui/` and a `docs/chat-sessions-design.md` file, without changing the kernel/runtime core. The comparison shows one commit ahead of `main`, with new frontend files and the design document only.

The current runtime is already close to the right low-level shape. It has a `RunController`, `RunStore`, `RunBus`, approval broker, cancel endpoint, SSE event endpoint, run listing, run summary, fork endpoint, and artifact serving. The SSE endpoint emits events as named SSE messages with `id: <seq>`, `event: <event.type>`, and JSON `data`.

The immediate technical gap is also clear: `RunController.start_run` hardcodes `FakeModelProvider(_fake_responses(task))`, does not use the OpenAI-compatible provider path, and does not pass `stream=True` into `kernel.run(...)`.

The real provider already exists. `OpenAICompatibleProvider.from_env` reads `TINYAGENT_MODEL_BASE_URL`, `TINYAGENT_MODEL_API_KEY`, `TINYAGENT_MODEL_NAME`, timeout, context-window, max-output-token, and extra-body settings; it also implements both non-streaming `complete(...)` and streaming `stream(...)`.

So the smallest meaningful web-streaming milestone is not a new chat architecture. It is: make the existing runtime server instantiate the same real provider the CLI can instantiate, run the kernel with streaming enabled, and expose the same event stream over SSE.

## 3. What the event system already gets right

The best existing seam is `RunState.emit(...)`. It is the single event boundary. It increments `seq`, writes durable events to `events.jsonl`, and emits both durable and ephemeral events to a live sink. This is exactly the kind of primitive that can serve CLI, SDK, web UI, TUI, and tests.

The event model also already has the right separation:

Durable events are the replayable trace: run lifecycle, turn lifecycle, model calls, tool calls, approvals, artifacts, workspace mutations, etc.

Ephemeral events are live-only deltas: `model.text.delta`, `model.reasoning.delta`, `model.tool_call.args.delta`, tool output deltas, command output deltas. They are streamed to sinks but not written to `events.jsonl`.

Large payloads are kept out of the event stream. Events refer to artifacts instead. This matters because coding agents generate large command outputs, diffs, context reports, request payloads, response payloads, and final files.

The model streaming path is also already coherent. `complete_model_call(...)` normalizes provider stream chunks into `ModelDelta`s, emits `model.text.delta`, reasoning deltas, tool-call argument deltas, usage, and final tool-call assembly events, and then returns a normal `ModelResponse` to the rest of the kernel.

That is a strong pattern: streaming is not a frontend concern. Streaming is a model-provider concern normalized into core events.

## 4. What is missing in the core/service boundary

The missing pieces are not primarily React pieces.

The first missing piece is shared provider construction. Today, `agentctl run` has `_model_for(...)`, while `agentd/runtime.py` hardcodes fake responses. The runtime, CLI, eval runner, SDK, and any future server mode should all use the same provider factory. The current CLI path already proves this shape: `agentctl run` and `agentctl eval` call `_model_for(...)`; `serve` does not.

The second missing piece is a real visibility/privacy filter at the runtime boundary. Events have `visibility` values of `internal`, `debug`, `user`, and `public`, plus debug-level helpers.  The web UI must not be trusted as the privacy boundary. The server should filter before sending SSE events. The UI can also ignore hidden events defensively, but that is not sufficient.

The third missing piece is live-stream retention. `RunBus` currently stores live events in memory while a run is active and then `cleanup_run(...)` removes them when the kernel thread exits.  Since ephemeral deltas are not persisted, a client that reconnects after completion cannot recover token deltas. That is acceptable if `final.md` is always available, but the runtime should avoid dropping live events before connected SSE clients have a chance to drain them. A small TTL-based live buffer would be more robust than immediate cleanup.

The fourth missing piece is stable event-to-surface identity. The chat reducer currently often keys tool UI state by `event.item_id`, but actual tool events usually carry `data.tool_call_id`, and many tool execution events do not set `item_id`. The reducer will therefore fail to correlate “tool assembled”, “tool started”, and “tool completed” reliably.

The fifth missing piece is durable final answer recovery. The UI currently expects `model.message.completed.data.text`, but the design note says the actual event contains output metadata such as `content_chars` and `output_path`, not necessarily full text. The frontend must recover the final assistant answer from the artifact endpoint when live deltas are absent or incomplete.

The sixth missing piece is a canonical conversation/message ledger. `Transcript` is useful but not sufficient as a full session-history primitive today. It records metadata for model responses, tool calls, tool results, finish gates, and compaction, but model response content is represented by length and artifact refs rather than inline full assistant messages.  The context builder currently builds context from the current task, environment, project instructions, context plan, observations, checkpoint, ContextFS index, and recent tool steps; it does not reconstruct a multi-turn chat history from prior user/assistant messages.

That is the important “hole in the armour”: the run trace is good, but the conversation ledger needed for sessions is not yet first-class.

## 5. What other agents suggest

The useful pattern across Codex, Pi, Hermes, and OpenCode is that they separate the live execution unit from the persisted conversation/session unit.

Codex is the cleanest conceptual comparison. Its protocol document defines the core engine as separate from the UI. The UI sends operations through a submission queue; the core emits events through an event queue. A `Session` is current configuration and state. A `Task` is work started by user input. A task consists of one or more `Turn`s, and the system has at most one task running in a session at a time. The document explicitly says the UI may be CLI/TUI or GUI, while Codex is intended to be operated by arbitrary UI implementations.

Codex also persists sessions as rollout JSONL files. Its rollout recorder is specifically described as persisting session rollouts so sessions can be replayed or inspected later; resumed sessions open the existing rollout file in append mode and load rollout items back into `InitialHistory::Resumed`.

Pi has a very lightweight but powerful session model. It stores sessions automatically under `~/.pi/agent/sessions/`, organized by working directory; each session is a JSONL file with a tree structure; it supports continuing, browsing, no-session mode, explicit session selection, and forking. It also has `/tree`, `/fork`, `/clone`, `/compact`, and an interactive session picker. ([Pi][1])

Pi’s important design signal is not the exact directory path. It is that sessions are branchable trees, not just linear chats. That matters for coding agents because users often ask “try approach A,” then later branch back and ask for approach B. Pi’s docs describe session entries linked by `id` and `parentId`, enabling branching without creating separate disconnected files. ([Pi][2])

Hermes goes heavier. It stores session metadata and full message history in `~/.hermes/state.db` with SQLite FTS5 search, while also keeping JSONL transcripts under `~/.hermes/sessions/`. It tracks source platform, user ID, title, model config, system prompt snapshot, full messages, tool calls, tool results, token counts, timestamps, and parent session IDs. It also supports CLI resume by latest session, by ID, and by title.

Hermes’s important design signal is cross-surface persistence. CLI, Telegram, Discord, Slack, WhatsApp, cron, API server, and other sources all map into sessions with explicit source metadata. That is relevant because tinyagent’s surfaces should likewise be adapters over the same session/run substrate.

OpenCode presents the product-surface side. Its official docs describe terminal, desktop, and IDE extension availability; its CLI includes `opencode serve` for a headless HTTP server, `opencode session list`, `opencode export`, and `opencode import`. Its site also advertises multi-session and share links, while its agent docs describe primary agents and subagents, including child-session navigation. ([OpenCode][3])

The lesson is not “copy any one of them.” The lesson is: a serious coding agent eventually needs sessions, branching/forking, durable history, streamable events, resumability, provider config, and interface neutrality. But it does not need all of that in the first chat UI PR.

## 6. The design thesis

I would define tinyagent around four primitives:

A `Run` is one execution attempt for one user task. It may include many model/tool loops. It is replayable and inspectable.

A `Turn` is one user-visible interaction inside a session. In the current kernel, each run has exactly one `turn-0001`; that is fine for now.

A `Session` is a durable conversation/work stream composed of turns, where each turn can point to one run.

An `Event` is the only live observation stream. Surfaces do not receive special UI messages. They project events into their own UI state.

This keeps the kernel honest. The kernel remains a run engine. The runtime grows into an interface-neutral coordinator. The session layer becomes a lightweight persistence/indexing layer, not a second execution engine.

## 7. Recommended architecture

The architecture should have four layers.

Layer 1: `agentd.core`

This is the kernel and execution machinery: model calls, tool dispatch, policy, approvals, workspace, sandbox, context, compaction, transcript, events, artifacts.

This layer should not know about HTTP, React, SSE, browser sessions, web sockets, or frontend reducers.

Layer 2: `agentd.runtime`

This is the controller layer: start run, cancel run, approve, list runs, serve artifacts, stream events, create sessions, append messages to sessions, and select providers.

This layer may expose HTTP, but the internal controller should also be callable by an SDK or tests without HTTP.

Layer 3: `agentd.session`

This should be small at first. It owns session metadata, turn list, branch/fork pointers, prior-message reconstruction, and home/workspace indexing. It does not execute tools. It calls the runtime to start runs.

Layer 4: surfaces

CLI, chat UI, future TUI, SDK, evals, IDE plugins. They consume events and call controller operations. They do not construct `Kernel` directly unless they are intentionally using the low-level SDK.

This gives tinyagent a clean identity: one core, many surfaces.

## 8. The first streaming milestone

The first PR should not implement full sessions. It should make a single run stream correctly into the chat UI using the real provider path.

Concretely:

Add provider and streaming args to `agentctl serve`.

Current `serve` only accepts `--workspace`, `--host`, `--port`, and `--run-root`.  It should accept at least:

```text
agentctl serve \
  --provider openai-compatible \
  --workspace . \
  --host 127.0.0.1 \
  --port 8765 \
  --stream \
  --debug 0
```

Move provider construction out of `agentctl/cli.py` into `agentd.providers.factory` or similar.

A minimal shape:

```python
@dataclass(frozen=True)
class ProviderSpec:
    kind: Literal["fake", "openai-compatible"]
    model: str | None = None

def provider_for(spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
    ...
```

Then CLI, evals, serve, and SDK all call the same factory.

Extend `RuntimeConfig`.

```python
@dataclass(frozen=True)
class RuntimeConfig:
    workspace: Path
    run_root: Path
    provider_factory: Callable[[str], ModelProvider]
    stream: bool = True
    debug_level: int = 0
    workspace_mode: WorkspaceMode = "current"
    approval_mode: ApprovalMode = "yolo"
    sandbox_mode: SandboxModeInput = "none"
```

Then `RunController.start_run(...)` creates:

```python
kernel = Kernel(
    model=self.config.provider_factory(task),
    profile=ApexCoderProfile(),
    tools=default_tools(),
    policy=default_policy(),
    approval_handler=self.approvals,
    event_sink=self.bus,
    stream=self.config.stream,
    workspace_mode=self.config.workspace_mode,
    approval_mode=approval_mode,
    sandbox_mode=self.config.sandbox_mode,
)
```

And passes `stream=self.config.stream` into `kernel.run(...)`.

Add event filtering before SSE writes.

The runtime should use `event_debug_level(event)` and `event.visibility`. A browser/default public surface should receive `public` and `user` events at debug level 0. Internal reasoning should never leak to the default web UI. The event system already has debug-level machinery; use it at the HTTP boundary.

Add a small terminal live-buffer retention policy.

Do not call `bus.cleanup_run(run_id)` immediately, or change it to mark a terminal time and purge after a TTL, for example 2–5 minutes or after max N events. That avoids losing ephemeral tail events for clients that are actively connected but scheduled slightly behind the run thread.

This is not red tape. It is a robustness fix to the current stream path.

## 9. Chat UI should become a reducer over real events

The chat UI should not invent an approximation of events. It already has `startRun`, `streamRunEvents`, `cancelRun`, and `decideApproval` in `api.ts`, which is the right basic shape.

But `useRun.ts` should be corrected to treat tinyagent events as the source of truth.

Tool identity should use `data.tool_call_id`, not `event.item_id`.

Reasoning deltas should only render when `event.visibility` is `public` or `user`, and even then only if the payload contains a displayable `delta`.

Assistant text should append from `model.text.delta`.

`model.message.completed` should not assume `data.text`. If the live answer is empty or incomplete, fetch the event’s `output_path` artifact, such as `final.md`.

Approval UI should use `approval_id`, `tool`, `command`, `args_preview`, and risk fields from the approval event payload.

Artifacts should store enough data to produce links back through `/api/runs/{run_id}/artifacts/{path}`.

Reconnect should track `after_seq`. But the UI must understand the difference between live-only replay and durable replay: after completion, text deltas are gone, so final answer recovery comes from artifacts.

This keeps the UI thin and testable. The reducer can be frontend code, but the concepts should mirror the event stream exactly.

## 10. Session design: choose sequence-of-runs first

I would choose a hybrid of “session = sequence of runs” first, with one important addition: a canonical session message ledger.

Do not make `Kernel.run_session(...)` the first session implementation. That would require changing `RunState.done`, cancel semantics, approval scopes, budget semantics, turn lifecycle, workspace cleanup, and `_run_loop` termination. The current kernel sets `state.done` when a run finishes or fails; `finish(...)`, `fail(...)`, and cancel all assume done means terminal.  Changing that now would be invasive.

Do not implement `Kernel.continue_run(state, message)` yet either. That would preserve in-memory context, but it would also force you to reset terminal state and split “turn done” from “run done.” That is a valid future design, but it is not the smallest next step.

Instead:

A session is a durable controller-level object.

Each user message creates one run.

Each run remains independently replayable and inspectable.

The session stores a canonical user/assistant/tool history sufficient to build context for the next run.

The session owns conversation-level metadata: title, workspace, provider profile, branch parent, active turn, current run, and prior turns.

The kernel gets one minimal extension: the ability to accept prior context.

The current context builder only includes the current task as `Task:\n{state.task}` and does not include prior session messages.  So the minimal kernel-level change is not a full session loop; it is an input-context seam.

Possible API:

```python
Kernel.run(
    task: str,
    *,
    prior_messages: Sequence[Message] = (),
    ...
)
```

or slightly more explicit:

```python
@dataclass(frozen=True)
class RunInput:
    task: str
    prior_messages: tuple[Message, ...] = ()
    attachments: tuple[InputAttachment, ...] = ()
```

Then `ContextBuilder.build(...)` can include a `conversation:history` context item before the current task.

The session controller becomes responsible for producing `prior_messages`.

That gives you multi-turn behavior without making the kernel long-lived.

## 11. But the session ledger must be real

This is the part I would be strict about.

Do not try to make session history out of `events.jsonl` alone. Events are observational. They are excellent for replay and UI streaming, but they are not the best canonical source for model-visible conversation state.

Do not rely on `Transcript` alone in its current form. It records useful tool/result metadata, but not full assistant content inline.

Add a compact session message ledger.

For each turn, store:

```json
{
  "type": "turn.completed",
  "session_id": "...",
  "turn_id": "...",
  "run_id": "...",
  "parent_turn_id": null,
  "user_message": {
    "id": "...",
    "role": "user",
    "content": "..."
  },
  "assistant_message": {
    "id": "...",
    "role": "assistant",
    "content_artifact": "final.md",
    "content_preview": "...",
    "content_chars": 1234
  },
  "tool_summary": [
    {
      "tool_call_id": "...",
      "tool": "shell",
      "ok": true,
      "summary": "...",
      "artifact_refs": [...]
    }
  ],
  "token_estimate": 12345,
  "created_at": "..."
}
```

This ledger is not a replacement for run traces. It is the durable conversation skeleton used to build future context.

The ledger can be small. It does not need to store every command output inline. Tool results can be summarized and link to run artifacts. That preserves the tinyagent style: large data lives in artifacts; small metadata lives in records.

## 12. Storage layout

I would reconcile home-directory session listing with workspace-rooted runs like this:

```text
~/.tinyagent/
  config.toml
  sessions/
    index.jsonl
    <session_id>/
      session.json
      turns.jsonl

<workspace>/.tinyagent/
  runs/
    <run_id>/
      events.jsonl
      transcript.json
      metrics.json
      final.md
      artifacts/
      context/
```

The home directory gives a global “resume” list like Codex, Pi, Hermes, and OpenCode.

The workspace run directory preserves existing replay/inspect/fork behavior.

Each session turn references a workspace run:

```json
{
  "turn_id": "turn_...",
  "run_id": "run_...",
  "workspace": "/path/to/repo",
  "run_path": "/path/to/repo/.tinyagent/runs/run_...",
  "parent_turn_id": null,
  "status": "completed"
}
```

This avoids forcing `agentctl replay` to learn sessions immediately. Existing run tools keep working. Later, `agentctl session inspect` or `agentctl session replay` can be added as a higher-level view.

For branching, copy Pi’s conceptual model, not necessarily its exact implementation: turns can have `parent_turn_id`. A session can be a tree. The active branch is just a pointer to the current leaf. Pi’s docs explicitly use an `id`/`parentId` tree structure to enable branching and navigation. ([Pi][2])

## 13. Session API shape

Keep `/api/runs` unchanged.

Add sessions as a sibling resource later:

```text
POST /api/sessions
GET  /api/sessions
GET  /api/sessions/{session_id}

POST /api/sessions/{session_id}/messages
GET  /api/sessions/{session_id}/events?after_seq=N

POST /api/sessions/{session_id}/cancel-turn
POST /api/sessions/{session_id}/end
POST /api/sessions/{session_id}/approve
POST /api/sessions/{session_id}/fork
```

But implement this only after single-run streaming is correct.

`POST /api/sessions/{id}/messages` should return immediately:

```json
{
  "session_id": "sess_...",
  "turn_id": "turn_...",
  "run_id": "run_...",
  "status": "running"
}
```

The web UI can then stream either run events or session events.

For the first session implementation, I would not create a full session-level event stream. I would let the client stream the active run events using the returned `run_id`. Session events can be added once session branching/resume becomes real.

That avoids premature API expansion.

## 14. Provider config

Start with process-level provider config for `serve`.

```text
agentctl serve --provider openai-compatible --stream
```

Backed by env vars:

```text
TINYAGENT_MODEL_BASE_URL=http://127.0.0.1:8080/v1
TINYAGENT_MODEL_API_KEY=local
TINYAGENT_MODEL_NAME=<model-name>
```

This matches the current provider implementation.

Then add named provider profiles later:

```toml
[providers.local-llama]
kind = "openai-compatible"
base_url = "http://127.0.0.1:8080/v1"
api_key_env = "TINYAGENT_MODEL_API_KEY"
model = "qwen3-coder"

[providers.openai]
kind = "openai-compatible"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
model = "gpt-4.1"
```

Do not allow arbitrary browser-supplied provider base URLs by default. A web UI should select a configured provider name, not submit raw provider credentials and URLs unless the server is explicitly running in an unsafe local-dev mode.

This keeps the browser out of the trust boundary.

## 15. Approval and cancel semantics

For single-run streaming, keep the current semantics.

For sessions, distinguish:

Cancel active turn: cancels the active run but keeps the session alive.

End session: marks the session closed and releases any session-owned workspace/sandbox resources.

Approval scope should evolve from:

```text
once | run
```

to:

```text
once | turn | session
```

But do not rename `run` immediately. For backward compatibility, treat `run` as `turn` inside session mode. Add `session` only once session-level approvals exist.

Codex’s protocol distinction is useful here: a session can have at most one active task, and interrupting a task does not necessarily destroy the session.  Tinyagent should adopt that distinction later.

## 16. Workspace and sandbox lifecycle

For now, single-run web streaming should use `workspace_mode="current"` unless explicitly overridden.

For sessions, workspace semantics become a serious coding-agent issue. If each turn creates a fresh worktree and tears it down, the session loses accumulated edits. If all turns use the current workspace, edits persist but safety is weaker.

The minimal session design should support a session-owned workspace lease:

```text
session.workspace_root
session.effective_workspace_root
session.workspace_mode
session.sandbox_mode
session.cleanup_policy
```

At first, this can be metadata only for `current` mode.

Later, if `worktree` mode becomes default for sessions, the controller should create the worktree at session start and clean it up at session end, not per turn.

This is one reason not to rush long-lived kernel sessions. Workspace lifecycle belongs in the runtime/session controller before it belongs in `_run_loop`.

## 17. Compaction across turns

Do not implement cross-turn compaction as a kernel feature first.

Instead:

Each run can compact internally as it already does.

The session ledger should build prior context using a bounded history window plus optional summaries.

Add manual `/compact` or `POST /api/sessions/{id}/compact` later.

A compacted session turn can write a summary message into the ledger:

```json
{
  "type": "session.compacted",
  "covers_turns": ["turn_1", "turn_2", "..."],
  "summary_artifact": "session-summary-0001.md",
  "summary_preview": "..."
}
```

This follows the general direction of Pi and Hermes: compaction is a session operation that preserves continuity while reducing context pressure. Pi exposes `/compact`; Hermes creates lineage when compression continues a session. ([Pi][1])

## 18. The event contract for surfaces

Do not create a large formal event projection system yet. That is where the previous recommendation felt too heavy.

Instead, create a small “surface contract” document and tests around the existing event stream.

Minimum contract:

```text
run.started
turn.started
model.call.started
model.text.delta
model.message.completed
model.tool_call.assembly.completed
tool.execution.started
tool.execution.completed
tool.execution.failed
tool.execution.blocked
approval.requested
approval.resolved
artifact.created
artifact.materialized
workspace.mutation.detected
run.completed
run.failed
run.cancelled
```

Rules:

`seq` is monotonic per run.

`data.tool_call_id` is the tool correlation key.

`artifact_refs` and explicit artifact path fields are fetchable through the artifact endpoint.

`model.text.delta` is live-only.

`model.message.completed` or `final.md` is the durable answer fallback.

`visibility=internal` never leaves the public runtime stream.

Unknown event types must be ignored by surfaces.

This is enough for SDK, web, TUI, CLI, and eval adapters to behave consistently.

## 19. Implementation order

I would do this in five steps.

Step 1: Make the current run server real.

Add `agentctl serve --provider openai-compatible --stream --debug`.

Move provider construction into `agentd`.

Make `RuntimeConfig` carry provider factory, stream flag, debug level, workspace mode, approval mode, and sandbox mode.

Run kernel with `stream=True`.

Filter SSE events by visibility/debug level.

Retain terminal live events briefly instead of immediate bus cleanup.

This gives you real token streaming into the browser without changing kernel semantics.

Step 2: Harden chatui as a diagnostic surface.

Fix tool correlation to use `data.tool_call_id`.

Ignore non-user-visible reasoning.

Track `after_seq`.

Fetch final output artifact if no live answer was assembled.

Render approval request/resolution from actual event payloads.

Render artifact links through `/api/runs/{id}/artifacts/...`.

This makes chatui a useful probe of the runtime contract.

Step 3: Add tests around the surface contract.

Test that SSE includes `model.text.delta` when streaming is enabled.

Test that `internal` events are filtered from default web streams.

Test that tool-call assembly and tool execution correlate by `tool_call_id`.

Test that disconnect/reconnect after completion can recover durable final output.

Test that approval request/decision works over HTTP.

Step 4: Add a minimal session ledger.

Create `agentd/session.py` or `agentd/sessions/store.py`.

Store `session.json` and `turns.jsonl` under `~/.tinyagent/sessions/<session_id>/`.

Each turn creates one run and records the run reference.

Do not add full session SSE yet unless needed.

Add `agentctl session list`, `agentctl session resume`, or HTTP session endpoints only after the store works internally.

Step 5: Add prior-context injection.

Add `prior_messages` or `RunInput` to the kernel.

Teach `ContextBuilder` to include a bounded `conversation:history` item.

Build that history from the session ledger.

Keep each turn independently replayable by writing the exact prior-context snapshot into the run artifacts.

This is the first real core extension. It is small, but it unlocks multi-turn sessions without making the kernel long-lived.

## 20. What not to build yet

Do not build a full chat-session API before single-run streaming is proven.

Do not change `RunState.done` semantics yet.

Do not add SQLite yet. Hermes needs SQLite because it is a multi-platform persistent personal agent with full-text search and many message sources. Tinyagent can start with JSONL and add SQLite indexing later if session listing/search becomes slow. Hermes’s SQLite design is powerful, but it is heavier than tinyagent needs right now.

Do not make React types part of the core.

Do not create UI-specific event names.

Do not make the browser responsible for provider configuration, authorization, or privacy filtering.

Do not make “chat” the product center. The product center is the coding agent runtime.

## 21. The main design decision

The answer I would commit to is:

Tinyagent should keep `Kernel.run` as the fundamental execution unit, make the runtime server a real event-streaming surface over that unit, and later add sessions as a lightweight controller-level sequence/tree of runs with a canonical message ledger.

That gives you the benefits that Codex, Pi, Hermes, and OpenCode converge on — resume, branch, search, multi-surface interaction, and durable history — without prematurely turning the kernel into a long-lived chat loop.

The first concrete milestone is therefore not “chat sessions.” It is:

```text
real provider + stream=True + filtered SSE + robust event reducer + final artifact fallback
```

Once that works, the missing core seams will be obvious under real use: prior context, session ledger, workspace lease, approval scope, cancel scope, and compaction across turns. Those should be added in that order.

[1]: https://pi.dev/docs/latest/sessions?utm_source=chatgpt.com "Pi Coding Agent"
[2]: https://pi.dev/docs/latest/session-format?utm_source=chatgpt.com "Pi Coding Agent"
[3]: https://opencode.ai/?utm_source=chatgpt.com "OpenCode | The open source AI coding agent"
