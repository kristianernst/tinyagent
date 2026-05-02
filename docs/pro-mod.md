One big recommendation:

# Make the next Tinyagent milestone the **Interaction Ledger**

Do not add a new “Cursor-like SDK layer,” MCP, memory, subagents, TUI, persistent terminal, or more provider breadth yet. Instead, make Tinyagent’s next core unit a small, event-sourced **Interaction Ledger** that unifies four things currently at risk of becoming separate feature tracks:

```text
streaming
step cancellation
tool-call assembly
workspace / approval safety

```

The shape should be:

```text
Run
  Turn
    Step
      model_call | tool_execution | approval_wait | artifact_finalization

Live interaction updates
  derived from events, not source of truth

Durable semantic events
  source of truth

Artifacts / conversation view
  materialized projections

```

Cursor’s `InteractionUpdate` is useful because it names the fine-grained live layer: `text-delta`, `thinking-delta`, `partial-tool-call`, `step-started`, `step-completed`, `turn-ended`, and `shell-output-delta`. But Tinyagent already has the better substrate: event envelopes with `visibility` and `durability`. So copy the **layering**, not the object model.

Given your stack, I would finish the current PR chain through [#15 Add run control cancellation](https://github.com/kristianernst/tinyagent/pull/15), then make the next stack one coherent milestone:

```text
M2: Interaction Ledger + Workspace Envelope + Approval

```

Not three milestones. One. These belong together because they define when something is allowed to happen, what exact step is happening, how it streams, how it is cancelled, and what becomes durable.

## The core rule

Tinyagent should adopt this invariant:

```text
Nothing mutating happens unless the ledger knows:
  where it is allowed to mutate,
  which turn requested it,
  which step owns it,
  which model call proposed it,
  which policy decision allowed it,
  whether approval was required,
  and what final durable result was committed.

```

That is the harness kernel.

Everything else is adapter/product surface.

## The minimal model

Use this hierarchy:

```text
run_id
  durable execution trace

turn_id
  one user intent / prompt episode

step_id
  cancellable execution unit

model_call_id
  one provider request

tool_call_id
  model-proposed tool call

tool_execution_id
  actual dispatched tool execution

```

Do not add a full `Item` dataclass yet. Keep `item_id` / `parent_item_id` as correlation fields until a real interactive protocol needs materialized items.

## Event taxonomy to implement

The next event set should be small and exact.

For turns:

```text
turn.started
turn.completed
turn.interrupted
turn.failed

```

For steps:

```text
step.started
step.completed
step.failed
step.cancel.requested
step.cancelled
step.timeout
step.idle_timeout

```

For model streaming:

```text
model.call.started
model.text.delta
model.reasoning.delta
model.reasoning.completed
model.tool_call.assembly.started
model.tool_call.args.delta
model.tool_call.assembly.completed
model.tool_call.assembly.failed
model.message.completed
model.cancelled
model.timeout
model.idle_timeout

```

For tool execution:

```text
tool.execution.started
tool.execution.output.delta
tool.execution.output.snapshot
tool.execution.completed
tool.execution.failed
tool.execution.cancelled
tool.execution.blocked

```

For shell:

```text
command.started
command.output.delta
command.completed
command.failed
command.cancelled
command.timeout

```

For workspace and approval:

```text
workspace.opened
workspace.boundary
workspace.dirty.detected
workspace.mutation.planned
workspace.mutation.started
workspace.mutation.completed
workspace.escape.detected
worktree.created

policy.evaluated
approval.requested
approval.resolved
approval.expired

```

For artifacts:

```text
artifact.finalization.started
artifact.materialized
artifact.finalization.completed
artifact.finalization.failed

```

The important split is this:

```text
model.tool_call.assembly.*
  means the model is producing a proposed tool call

tool.execution.*
  means Tinyagent actually ran the tool

```

Do not collapse those. Cursor’s `partial-tool-call`, `tool-call-started`, and `tool-call-completed` make that separation more obviously necessary.

## Durability rule

Use Cursor’s `InteractionUpdate` idea as a live projection:

```text
model.text.delta                 live-only
model.reasoning.delta            live-only
model.tool_call.args.delta        live-only
command.output.delta              live-only by default
tool.execution.output.delta       live-only by default

```

Then commit only completed semantic facts durably:

```text
model.message.completed
model.tool_call.assembly.completed
tool.execution.completed
tool.execution.output.snapshot
command.completed
turn.completed

```

This gives Tinyagent the right invariant:

```text
Streaming is first-class, but incomplete stream fragments are not history.

```

That matters most for cancellation. If the user cancels mid-model stream, partial assistant text may have been displayed, but it should not become final assistant content unless explicitly promoted.

## Policy change

Change:

```python
PolicyDecision(allowed: bool, reason: str)

```

to:

```python
PolicyDecision(
    kind: Literal["allow", "deny", "needs_approval"],
    reason: str,
    approval: ApprovalRequest | None = None,
)

```

This is not UI. It is core semantics.

Minimal approval object:

```python
@dataclass(frozen=True)
class ApprovalRequest:
    approval_id: str
    run_id: str
    turn_id: str
    step_id: str
    action_kind: Literal[
        "shell",
        "patch",
        "network",
        "workspace_escape",
        "dirty_mutation",
        "unknown",
    ]
    tool_name: str
    cwd: str
    args_preview: str
    command: str | None
    risk: Literal["low", "medium", "high"]
    scope_options: tuple[Literal["once", "run"], ...]

```

Resolution:

```python
@dataclass(frozen=True)
class ApprovalResolution:
    approval_id: str
    decision: Literal["approved", "denied", "cancelled", "expired"]
    scope: Literal["once", "run"] | None
    reason: str | None

```

Only support these scopes initially:

```text
once
run

```

No permanent grants yet.

## Workspace model

Use this CLI surface:

```text
--workspace-mode auto|worktree|current
--approval-mode never|on-request|yolo
--sandbox-mode none

```

Keep `sandbox-mode` honest. Until Tinyagent has actual OS/container enforcement, the only truthful default is:

```text
sandbox_mode = "none"
sandbox_enforced = false

```

Define a workspace envelope before any mutation:

```python
@dataclass(frozen=True)
class WorkspaceEnvelope:
    root: Path
    mode: Literal["auto", "worktree", "current"]
    worktree_path: Path | None
    git_head_before: str | None
    dirty_state_before: DirtyState
    allowed_roots: list[Path]
    sandbox_mode: Literal["none"]
    sandbox_enforced: bool

```

The key invariant:

```text
No mutating tool executes before workspace.boundary exists.

```

`--approval-mode=yolo` should mean:

```text
auto-allow inside the workspace envelope

```

It should not mean:

```text
allow network
allow outside-root writes
allow destructive commands against arbitrary paths
hide dirty worktree risk

```

YOLO is acceptable only when bounded.

## State fields

Add only what pays rent:

```python
current_turn_id: str | None
current_step_id: str | None
current_model_call_id: str | None

terminal_status: Literal[
    "completed",
    "failed",
    "cancelled",
    "interrupted",
    "timed_out",
] | None

workspace: WorkspaceEnvelope | None
pending_approvals: dict[str, ApprovalRequest]
approval_grants: dict[str, ApprovalGrant]

finalization_attempted: bool

```

For correlation, add IDs into event `data` or reserved envelope fields:

```text
step_id
model_call_id
tool_call_id
tool_execution_id
approval_id

```

## CLI behavior

Non-interactive:

```text
--approval-mode never
  needs_approval -> deny
  emit approval.requested
  emit approval.resolved(decision="denied", reason="approval_mode_never")
  emit tool.execution.blocked

```

Interactive:

```text
--approval-mode on-request
  needs_approval -> prompt
  approved once -> execute current action only
  approved run -> grant for this run only
  denied -> block
  timeout/cancel -> deny/fail closed

```

YOLO:

```text
--approval-mode yolo
  safe in-envelope mutations -> allow
  outside envelope -> deny or require explicit unsafe flag
  network -> deny or require explicit unsafe flag
  dirty mutation -> allow only if policy says dirty state is acceptable

```

Unsafe flags, if needed, should be ugly and explicit:

```text
--unsafe-allow-network
--unsafe-allow-outside-workspace

```

Do not call them “advanced” or “full access.” Make the risk visible.

## Tests that define the milestone

This milestone is done only when these tests pass.

Cancellation:

```text
cancel during model text stream
cancel during partial tool-call args
cancel during shell command
cancel during approval wait
cancel during artifact finalization
timeout during non-streaming provider call
idle timeout during streaming provider call

```

Assertions:

```text
prior completed steps remain durable
active step is cancelled/timed out
partial assistant deltas are not final assistant content
tool process group is terminated
terminal status is honest
final artifacts are attempted

```

Streaming/tool-call assembly:

```text
text-delta only
thinking-delta only
partial tool-call args then completed tool call
partial malformed JSON then assembly failure
tool call emitted but policy blocks execution
tool call assembled but approval denied

```

Workspace:

```text
clean git repo current mode
dirty git repo current mode
dirty git repo worktree mode
patch inside root
patch outside root
shell redirect outside root
destructive shell command
network-looking command

```

Approval:

```text
allow
deny
needs_approval approved once
needs_approval approved for run
needs_approval denied
needs_approval expired
approval-mode never fail-closed
approval-mode yolo bounded to workspace

```

Replay/materialization:

```text
events.jsonl reconstructs turn timeline
events.jsonl reconstructs step timeline
events.jsonl reconstructs approval timeline
events.jsonl reconstructs tool execution timeline
final.md excludes cancelled partial model text
metrics.json records workspace_mode, approval_mode, sandbox_mode, sandbox_enforced
final.diff is generated but not treated as rollback

```

## What to explicitly not do in this milestone

Do not add:

```text
MCP
memory
subagents
TUI
semantic search
persistent terminal backend
OpenAI Responses provider
Anthropic provider
Gemini provider
LiteLLM gateway
external tracing
AG-UI
full Cursor/Codex app-server-style SDK
cloud runtime
plugin framework

```

Provider conformance is next, but not before the ledger is correct. You can keep the current OpenAI-compatible provider and fake provider while hardening the event model.

## The one-sentence version

Make Tinyagent’s next real core primitive a **cancellable, approval-aware, workspace-bounded interaction ledger**: live deltas are projections, durable events are history, steps are the cancellation unit, workspace is the safety boundary, and approval is a policy result.

That is the thing to build next.