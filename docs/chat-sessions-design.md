# Design question: multi-turn chat sessions on top of `agentd`

## Audience

You are reviewing this for a Python/runtime architecture decision. Answer with:
1. A recommended option for each open question (with trade-offs).
2. A concrete API surface (endpoints + payloads + state ownership).
3. A migration path that keeps the existing single-shot `/api/runs` endpoint and the existing CLI working unchanged.

Do not optimise for the chat UI specifically — `agentd` is the core; the chat UI is one of N possible front-ends. CLIs, evals, IDE plugins, and external orchestrators all consume the same surface.

---

## Project shape

This repo is a small general-purpose agent harness, organised as:

- `agentd/` — the runtime library (Python). Public concepts are `Kernel`, `RunState`, `Profile`, `Tool`, `PolicyEngine`, `Transcript`, `Event`, `Workspace`, model providers.
- `agentctl/` — CLI front-end (`run`, `replay`, `inspect`, `fork`, `serve`, `eval`).
- `chatui/` — Vite + React + TypeScript SPA that talks to `agentd` over HTTP/SSE. Recently added; one consumer of the runtime, not part of the core.

Run artifacts (events, transcript, request/response payloads, command outputs, context snapshots, diffs) are written under `<workspace>/.tinyagent/runs/<run_id>/`. Recent commits include "Add run server and SSE event stream (#38)" and "Add first enforced sandbox backend (#40)".

`README.md` summary: minimal CLI-first agent. Default profile is `apex-coder` exposing only `shell` and `apply_patch`. JSONL traces. Fake provider for deterministic tests; `OpenAICompatibleProvider` for real models.

---

## What the kernel does today (single-run model)

`Kernel.run(task, *, workspace, run_id, output_dir, stream, event_sink, cancel_token, workspace_mode, approval_mode, sandbox_mode, parent_run_id, parent_event_id, branch_name) -> RunState`

`agentd/kernel.py`, around line 96. Behaviour:

1. Resolve workspace via `prepare_workspace` (auto / worktree / current). Sandbox backend chosen here.
2. Build a fresh `RunState` (`agentd/state.py`, dataclass with ~50 fields including `transcript: Transcript`, `tool_steps`, `pending_approvals`, `approval_grants`, `context_state`, `compaction_count`, `seq`, `done`, `terminal_status`, etc.).
3. Emit `run.started`, `workspace.opened`, `workspace.boundary`, `shell.preflight.completed`, `contextfs.index.updated`.
4. `state.start_turn("turn-0001")` — note the kernel hardcodes a single turn id.
5. Enter `_run_loop(state, stream=use_stream)`:

```python
while not state.done:
    state.raise_if_cancelled()
    if self._budget_exhausted(state): return
    if not self.profile.should_continue(state):
        state.finish("Run finished by profile."); return
    visible_tools = list(self.profile.visible_tools(state, self.tools))
    built_context = self._build_context(state, visible_tools)   # builds messages from task + transcript
    if self._should_compact(state): self._compact(state); ...
    # model.call.started / model.text.delta / model.tool_call.assembly.completed / model.call.completed
    response = call_model(...)
    if response.tool_calls:
        for call in response.tool_calls:
            run_policy_and_approval(call)
            execute_tool(call)
            transcript.record_tool_call(...); transcript.record_tool_result(...)
    elif response.content:
        decision = self._before_finish(state, response)
        if decision.allow: state.finish(response.content); return
        else: transcript.record_finish_gate(...); continue   # loop again with the gate message
    else:
        state.fail("Model returned no content and no tool calls."); return
```

6. Finally block: `_finalize_artifacts`, `state.finish_turn()`, `_finalize_run`, `write_run_outputs`.

**Key observations**

- `_run_loop` is a single agentic turn that may make many model calls (one per tool round-trip). It exits as soon as the model produces final text and the finish-gate allows it.
- The "task" is a single string. Multi-message conversation history is **not** part of the public API — internally, only `Transcript` records grow during one run. The user's first message is `state.task`.
- `state.start_turn("turn-0001")` is called exactly once. `turn_count` increments here. There is no kernel-level concept of "turn 2", although the event grammar has `turn.started` / `turn.completed` / `turn.interrupted` / `turn.failed` and every event carries an optional `turn_id`.
- The `Transcript` (`agentd/transcript.py`) is the canonical record of what happened in a run: `model_response`, `tool_call`, `tool_result`, `finish_gate`, `compaction`. It is built up during `_run_loop` and validated at the end (no orphan tool calls). It is suitable input to context building for a follow-up turn, but `_build_context` currently treats `state.task` as the only user message.
- Compaction (`agentd/context.py`) is run-scoped: checkpoints, compaction count, and context artifacts live on `RunState`. They survive across model calls within one run, not across runs.
- Approvals: `ApprovalHandler.resolve(request, state)` blocks the kernel thread until the broker resolves. `ApprovalBroker` in `agentd/runtime.py` is keyed on `(run_id, approval_id)`.
- Workspace: `prepare_workspace` may create a worktree or worktree-like sandbox keyed to the run. After the run completes, the worktree is cleaned up (depending on mode).
- Cancel: `CancelToken` is passed in. `run.cancel.requested` → kernel raises `RunCancelled` at the next `raise_if_cancelled()`.

---

## What the runtime server does today

`agentd/runtime.py`. `ThreadingHTTPServer` with these endpoints:

- `POST /api/runs {task, run_id?, approval_mode?}` — `RunController.start_run` spawns a daemon thread that calls `kernel.run(task, ...)` once. Hardcodes `model = FakeModelProvider(_fake_responses(task))`, `profile = ApexCoderProfile()`, `tools = default_tools()`, `policy = default_policy()`, `workspace_mode = "current"`. Returns `{run_id, run_path, status: "running"}`.
- `POST /api/runs/{id}/cancel {reason?}` — calls `cancel_token.cancel(reason)` and `ApprovalBroker.cancel_run`.
- `POST /api/runs/{id}/approve {approval_id, decision, scope?, reason?}` — resolves a pending approval through the broker.
- `POST /api/runs/{id}/fork {at}` — `fork_run` creates a fork dir from a recorded run.
- `GET /api/runs` / `GET /api/runs/{id}` — list and summarise (reads `metrics.json` or events.jsonl from disk).
- `GET /api/runs/{id}/events?after_seq=N` — SSE stream. Backed by `RunBus` (in-memory, per-run event list with a `Condition`) plus disk events via `RunStore.events`. Stops when a terminal event is seen or the run is no longer active and the bus is drained.
- `GET /api/runs/{id}/artifacts/{path}` — serves files under `<run_dir>/...`.

When the kernel thread exits, the controller calls `bus.cleanup_run(run_id)` and `approvals.cleanup_run(run_id)`. The disk events.jsonl persists; the in-memory bus does not.

`Kernel(model=…, profile=…, tools=…, policy=…, approval_handler=approvals, event_sink=bus, …)` is instantiated **per run**.

`OpenAICompatibleProvider` exists (`agentd/providers/openai_compat.py`) and reads from env vars (`TINYAGENT_MODEL_BASE_URL`, `TINYAGENT_MODEL_API_KEY`, `TINYAGENT_MODEL_NAME`, `TINYAGENT_MODEL_TIMEOUT_SECONDS`, `TINYAGENT_MODEL_CONTEXT_WINDOW`, `TINYAGENT_MODEL_MAX_OUTPUT_TOKENS`). It is wired into `agentctl run --provider openai-compatible` but **not** into the runtime server (`runtime.py` hardcodes `FakeModelProvider`).

---

## What the chat UI needs (one consumer)

- A **chat** is a sequence of user messages → assistant turns. Each turn is one or more model calls + tool calls + a final assistant message.
- The user expects context, compaction, and the transcript to persist across turns inside a chat.
- The UI also expects to: cancel mid-turn, approve/deny, see streaming `model.text.delta` and `model.reasoning.delta`, see tool call pills, and see new artifacts in a side panel.
- The user has a model running on `llama.cpp` at `http://127.0.0.1:8080`. So the runtime needs to use `OpenAICompatibleProvider` with that base URL, configured per-server-process (env or config file).

---

## Open design questions

### Q1. Should a "chat session" be a first-class concept in `agentd`?

There are three options. Pick one and justify.

**Option A — Long-lived kernel.run, queue-driven.**
Add `Kernel.run_session(input_queue, *, workspace, ...)`. The kernel thread loops:
```
state.start_turn(f"turn-{n:04d}")
wait for next user_message on input_queue (blocking)
state.task = message  # or extend state with a messages list
run agentic sub-loop until model finishes
state.finish_turn()  # but state.done stays False
n += 1
```
The session ends when (a) the queue is closed, (b) cancel is invoked, or (c) a budget across the session is exhausted.

Pros: one `RunState`, one workspace, one transcript, one compaction history — natural home for context evolution. Approvals key off `(session_id, approval_id)`. Sandbox/worktree set up once.

Cons: changes `RunState.done` semantics (currently terminal); introduces blocking I/O in the kernel; budgets are currently per-run, so we'd need session-level budgets. The agentic sub-loop today exits when `state.done` is set — every public terminal helper (`fail`, `finish`, `request_cancel`) flips `done`. Untangling "turn-terminal" from "session-terminal" is invasive.

**Option B — Session = sequence of runs, transcript replayed.**
A "session" is a controller-level abstraction, not a kernel concept. Each user message starts a new `kernel.run(...)` with the prior transcript fed in as messages. The kernel grows a `prior_transcript: Transcript | None` parameter that `_build_context` uses ahead of `state.task`.

Pros: kernel changes are minimal — add a `prior_transcript` arg and have `_build_context` prepend it. Workspace + sandbox are set up per turn (acceptable for `mode=current`; expensive for `mode=worktree`). Each turn is a standalone replay-able run with its own events.jsonl. Existing budgets/compaction stay per-run.

Cons: per-turn worktree set-up/tear-down. Compaction state doesn't carry across turns by default — would have to serialise/deserialise `context_state`, `compaction_count`, `context_checkpoint`, etc. Transcript artifacts duplicate between runs unless we store the canonical session transcript at the controller layer and rebuild messages from it.

**Option C — Session is a controller construct, kernel changes minimally to accept incremental messages.**
Same `Kernel.run()` signature but with `task: str | list[Message]`, plus a separate `Kernel.continue_run(state, message)` that re-enters `_run_loop` after appending the new user message to the transcript. The controller owns the long-lived `RunState` and feeds messages in.

Pros: kernel keeps a single in-memory state across turns (compaction, transcript, context_state all preserved naturally). Workspace setup runs once. Less invasive than A because the loop body doesn't change — only its entry point.

Cons: re-entering `_run_loop` requires resetting `state.done = False` for each new message. That's a clear contract violation of the current "done is terminal" invariant. We'd need to introduce a turn-terminal flag (e.g. `state.turn_done`) that the loop checks instead.

### Q2. What is the API shape?

If we accept "chat session as first-class", what should the HTTP surface look like? Specifically:

- `POST /api/sessions` — body? (workspace, approval_mode, profile, provider override)
- `POST /api/sessions/{id}/messages {text}` — does this return immediately (turn started) or block until the turn finishes? What's the `turn_id` contract?
- `GET /api/sessions/{id}/events?after_seq=N` — SSE for the whole session lifetime, including `session.started`, `turn.started`, `turn.completed`, `session.ended`. Should `turn.completed` close the stream, or stay open across turns?
- `POST /api/sessions/{id}/cancel` — does this cancel the active turn only, or end the session? How do clients distinguish?
- `POST /api/sessions/{id}/end` — explicit close to release the workspace/worktree.
- `POST /api/sessions/{id}/approve {approval_id, decision, ...}` — same broker semantics as runs, just keyed on session.
- Backwards compat: `/api/runs` stays as-is. Are sessions implemented as a sibling resource, or layered (a session is just a run with extra abilities)?

How do we represent "the turns in a session" in `GET /api/sessions/{id}`? Cite the existing run-summary shape (see `RunStore.run_summary`).

### Q3. Where do session artifacts live on disk?

Today: `<workspace>/.tinyagent/runs/<run_id>/{events.jsonl, transcript.json, metrics.json, artifacts/...}`.

Options:

1. `<workspace>/.tinyagent/sessions/<session_id>/turns/<turn_id>/...` — turns are sub-runs.
2. `<workspace>/.tinyagent/sessions/<session_id>/{events.jsonl, transcript.json, artifacts/...}` — single events log spanning all turns.
3. `~/.tinyagent/sessions/<session_id>/...` — global, machine-wide store; per-workspace is dropped or symlinked.

Which preserves `agentctl replay` and `agentctl inspect` for chats? Should those tools learn about sessions, or should each turn remain individually replayable?

The user wants a Codex-like "install and run" experience: the binary creates `~/.tinyagent/` on the user's home and stores sessions there by default. But `agentd` itself is workspace-rooted today (the workspace is the agent's working set; runs co-locate with it). How do we reconcile per-workspace artifacts with home-dir session listing?

### Q4. Provider configuration in the runtime server.

The chat user has llama.cpp on `http://127.0.0.1:8080/v1`. The runtime currently hardcodes `FakeModelProvider`.

Options:

1. **Process env**, read once in `create_runtime_server`. CLI: `agentctl serve --provider openai-compatible`. Provider chosen at startup; one provider per server.
2. **Per-session override**, sent in `POST /api/sessions {provider: {kind: "openai-compatible", base_url, model, ...}}`. Server validates against a whitelist.
3. **`~/.tinyagent/config.toml` with named profiles**, e.g.
   ```toml
   [providers.local-llama]
   kind = "openai-compatible"
   base_url = "http://127.0.0.1:8080/v1"
   model = "qwen3-coder"

   [providers.openai]
   kind = "openai-compatible"
   base_url = "https://api.openai.com/v1"
   api_key_env = "OPENAI_API_KEY"
   model = "gpt-4o-mini"
   ```
   The server loads this on startup and exposes provider names via `GET /api/providers`. Sessions select by name.

Which fits "agentd is the core, chat UI is one consumer" best? How does this interact with `agentctl run --provider`?

### Q5. Compaction & context budgets across turns.

Current: compaction triggers inside `_run_loop` based on `_should_compact(state)`. Checkpoints are written to `state.context_state`. `RunBudgets.max_turns = 30`, `max_run_seconds = 600`.

If a session has multiple agentic turns, what happens to:

- `RunBudgets.max_turns` — does each user message reset the counter, or does the session share one budget?
- `max_run_seconds` — same question.
- Compaction checkpoints — do they survive across turns? If yes, where on disk? If no, the model loses context.
- `context_state.included` / `excluded` — currently rebuilt every model call from `state.transcript`. If transcript persists across turns, this works automatically; otherwise it doesn't.

### Q6. Approval scope.

`ApprovalGrant.scope ∈ {"once", "run"}`. A "run-scoped" grant lasts the lifetime of one run. In a session of many turns, what does "run scope" mean? Should we add `"session"` and `"turn"` scopes, or rename `"run"` to `"session"` if a session is now the unit?

### Q7. Cancel semantics across turns.

Currently `cancel_token.cancel()` flips `state.done = True` and the kernel exits. In a session, a user might want to:

- Cancel the in-flight turn but keep chatting.
- Cancel the entire session.

How should the API distinguish? Does Option A (long-lived kernel) require splitting `CancelToken` into a turn-scoped child of a session-scoped parent? Does it require a new `state.turn_cancel_token` so the session token survives?

### Q8. Sandbox/worktree lifecycle.

`prepare_workspace` may create a worktree under `.claude/worktrees/...`. In a session, the worktree must persist across turns (so file edits accumulate) but be cleaned up at session end. Today the cleanup happens implicitly when the run thread exits.

For Option A, where does session-end cleanup hook in? For Option B, do we keep the worktree alive between turns at the controller layer, or recreate it each turn?

---

## Constraints / non-negotiables

- The existing `POST /api/runs` and `agentctl run` paths must keep working unchanged. Sessions are additive.
- Events emitted today must keep their schema. New event types are fine; renaming/repurposing existing ones is not.
- The kernel must remain usable in a single-process, in-memory test (see `tests/test_kernel.py`) without a network server.
- Replay must keep working for any single turn captured to disk (`agentctl replay <run_dir>`). Whether session-level replay also exists is open.
- No required dependency additions for the core (FastAPI/Starlette/aiohttp etc.). The runtime is `http.server` based today; keep it that way unless there's a strong reason to change.

## What to deliver

1. A choice between Q1's A / B / C with justification, plus any hybrid.
2. A concrete API surface for Q2.
3. A directory layout for Q3 that reconciles workspace-rooted artifacts with home-dir session listing.
4. Provider config recommendation for Q4.
5. Short answers (1–3 sentences each) for Q5, Q6, Q7, Q8.
6. An implementation order: which kernel/state/runtime/CLI changes ship in which step, with the smallest first PR that makes the chat UI functional end-to-end against the local llama.cpp.
