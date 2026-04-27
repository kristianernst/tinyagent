Yes. We are still missing several event families. Reasoning is only one of them.

My recommendation is: **Tinyagent should adopt an “Items + Events” internal contract, inspired primarily by OpenResponses and Codex App Server, then expose adapters to AG-UI, MCP, A2A, and OpenTelemetry rather than making any one external protocol the core.**

The golden setup is:

```text
Internal core:
  Tinyagent Items + Tinyagent Events

Model/provider compatibility:
  OpenResponses-shaped adapter where possible

Frontend/UI compatibility:
  AG-UI adapter

Tool/data interoperability:
  MCP adapter

Agent-to-agent delegation:
  A2A adapter later

Observability export:
  OpenTelemetry GenAI spans/metrics later
```

That preserves Tinyagent’s own minimal kernel while avoiding protocol isolation.

## The main thing we were missing

Tinyagent currently mostly sees:

```text
run lifecycle
context built
model request/response
tool call
policy decision
command
patch
artifact
diff
compaction
```

That is a good local trace foundation. But compared to mature agent protocols, it is missing event families around:

```text
item lifecycle
content part lifecycle
reasoning lifecycle
tool argument streaming
tool output streaming
approval/interrupt/resume
state snapshots/deltas
resource/context changes
capability changes
artifact lifecycle
subagent/handoff/delegation
usage/cost/cache/latency
guardrails/safety checks
cancellation/retry/reconnect
multimodal inputs/outputs
source/citation/provenance
human elicitation
```

These are not all needed immediately, but the contract should leave room for them.

## Why OpenResponses matters

The OpenResponses spec is the best reference for the **model-facing item model**. Its key idea is that **Items are the fundamental unit of context**: an item can represent model output, a tool invocation, or reasoning state, and items are bidirectional, meaning they can be fed as input or emitted as output. It also treats streaming as semantic events rather than raw text chunks. This maps directly to what Tinyagent needs. ([Open Responses][1])

OpenResponses also gives the right lifecycle model: items have statuses such as `in_progress`, `incomplete`, and `completed`; streamable items begin with an added event, may emit content-part additions and deltas, and then close with content-part and item-done events. That is much richer than “model response arrived” and much cleaner than token-only streaming. ([Open Responses][1])

The OpenResponses reasoning model is also useful because it separates raw reasoning, encrypted reasoning, and reasoning summaries. That lets Tinyagent represent provider-sanctioned reasoning artifacts without treating hidden chain-of-thought as ordinary user-visible text. ([Open Responses][1])

## Why Codex matters

Codex App Server is the best reference for a **harness-facing protocol**. OpenAI describes Codex’s protocol around three primitives: **Item**, **Turn**, and **Thread**. An item is the atomic unit of input/output, a turn is one unit of agent work initiated by user input, and a thread is the durable container for an ongoing session. Items have a lifecycle: `item/started`, optional `item/*/delta`, and `item/completed`. ([OpenAI][2])

Codex also shows why a client-facing harness protocol should be richer than MCP alone. The App Server transforms low-level core events into stable UI-ready JSON-RPC notifications, supports approvals that pause the turn, and emits diffs and progress suitable for IDE and app clients. ([OpenAI][2])

The important lesson is not “copy Codex.” The lesson is: **a real coding harness needs thread/turn/item semantics and approval/diff/progress events, not just provider tokens.**

## Why AG-UI matters

AG-UI is the best reference for the **frontend-facing event surface**. It is explicitly an event-based protocol connecting agents to user-facing applications, with categories for lifecycle, text messages, tool calls, state management, activity, special/custom events, and reasoning events. ([AG-UI][3])

AG-UI’s own docs position it alongside MCP and A2A: AG-UI for agent-user interaction, MCP for tools/data, and A2A for agent-agent communication. That is exactly the split Tinyagent should preserve. ([AG-UI][4])

AG-UI also exposes event kinds Tinyagent should reserve for: state snapshots/deltas, tool-call start/args/end, step started/finished, and custom extensibility events. ([TanStack][5])

## Why MCP matters

MCP should influence Tinyagent’s tool and resource interfaces, but it should not become the internal harness protocol. MCP is a JSON-RPC based protocol for connecting LLM applications to tools, resources, prompts, and external context. It standardizes tool discovery and invocation, resource reading/subscription, prompts, roots, sampling, and elicitation. ([Model Context Protocol][6])

The important event families to copy from MCP are **capability changes**, **resource changes**, **progress**, **cancellation**, and **elicitation**. MCP’s latest spec includes notifications for tools/resources/prompts list changes, resource updates, roots changes, progress, cancellation, and initialized messages. ([OpenTelemetry][7])

MCP’s elicitation feature is especially relevant. It defines a way for a server to ask the user for structured input or direct them to an external URL for sensitive interactions, using `elicitation/create` and response actions like `accept`, `decline`, and `cancel`. Tinyagent will eventually need similar events for approvals, missing credentials, OAuth flows, and human-in-the-loop decisions. ([Model Context Protocol][8])

## Why A2A matters

A2A is relevant later, when Tinyagent delegates tasks to other agents or exposes itself as a remote agent. Google describes A2A as an open protocol for agents to communicate, securely exchange information, coordinate actions, discover capabilities through Agent Cards, manage long-running tasks, exchange messages, and produce artifacts. ([Google Developers Blog][9])

For now, Tinyagent should not implement A2A. But the internal contract should reserve:

```text
agent.delegation.started
agent.message.created
agent.artifact.created
agent.delegation.completed
agent.delegation.failed
```

That will make later A2A mapping straightforward.

## Why LangGraph, Vercel AI SDK, and OpenAI Agents SDK matter

LangGraph’s useful contribution is **stream modes**. It distinguishes streaming full state values, state updates, token messages, debug data, custom data, and event streams. Tinyagent should copy the idea that a single run can have different stream views: user-visible stream, debug stream, JSONL event stream, and replay trace. ([LangChain Docs][10])

The Vercel AI SDK is a good frontend-stream reference because it distinguishes plain text streams from richer data streams. It explicitly says text streams only support basic text and recommends data streams when tool calls or other data types are needed. Its data protocol includes reasoning parts, source parts, file parts, custom data parts, tool-input start/delta/available, tool-output available, step start/finish, abort, and finish. ([AI SDK][11])

The OpenAI Agents SDK reinforces the split between raw model events and higher-level run-item events. It also exposes lifecycle points that Tinyagent should support later: approvals, cancellation after current turn, handoffs, tool events, reasoning items, MCP approvals, and MCP tool listing. ([openai.github.io][12])

## Golden internal model

Tinyagent should use five core objects:

```text
Run
Turn
Item
Event
Artifact
```

Definitions:

```text
Run:
  One execution of Tinyagent against a task and workspace.

Turn:
  One model-call/tool-execution cycle inside a run.
  A run can contain many turns.

Item:
  A semantic object produced or consumed during a run.
  Examples: message, reasoning, tool_call, tool_result, command, patch, diff, approval, artifact, checkpoint.

Event:
  A state transition or delta for a run, turn, or item.

Artifact:
  Large or durable payload stored outside the event body.
  Examples: command output, model request, model response, raw stream, diff, checkpoint.
```

This is the core design:

```text
Events mutate or describe Items.
Items are replayable.
Artifacts hold large payloads.
Runs and turns provide boundaries.
```

## Golden item contract

Use an item model close to OpenResponses/Codex, but Tinyagent-specific.

```python
from dataclasses import dataclass, field
from typing import Any, Literal

ItemStatus = Literal[
    "queued",
    "in_progress",
    "blocked",
    "completed",
    "failed",
    "cancelled",
    "incomplete",
]

ItemKind = Literal[
    "message",
    "reasoning",
    "model_call",
    "tool_call",
    "tool_result",
    "command",
    "patch",
    "diff",
    "artifact",
    "context",
    "checkpoint",
    "approval",
    "elicitation",
    "state",
    "resource",
    "handoff",
    "subagent",
    "guardrail",
    "usage",
    "error",
]

@dataclass
class Item:
    id: str
    kind: ItemKind
    status: ItemStatus
    run_id: str
    turn_id: str | None = None
    parent_id: str | None = None
    provider_id: str | None = None
    title: str = ""
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
```

The important part is not the exact Python type. It is that every meaningful thing becomes an addressable item with a lifecycle.

Examples:

```text
message item:
  assistant final answer or user task

reasoning item:
  summary, visible provider thinking, encrypted state, signature

tool_call item:
  apply_patch or shell call requested by model

command item:
  shell command execution lifecycle

patch item:
  patch application and rollback lifecycle

approval item:
  human approval request/response

context item:
  built context snapshot, token estimate, AGENTS.md loaded

checkpoint item:
  compaction checkpoint

artifact item:
  final.diff, command output, raw model stream

handoff/subagent item:
  future delegated agent work
```

## Golden event envelope

Use a small CloudEvents-like envelope, but do not literally require CloudEvents for local JSONL. CloudEvents is useful as a general event-envelope reference because it standardizes common event metadata such as id, source, type, and JSON event format, but Tinyagent’s local trace can be leaner. ([GitHub][13])

```python
@dataclass(frozen=True)
class Event:
    id: str
    seq: int
    type: str
    time: str

    run_id: str
    turn_id: str | None = None
    item_id: str | None = None
    parent_item_id: str | None = None

    source: str = "tinyagent"
    visibility: Literal["internal", "debug", "user", "public"] = "debug"
    durability: Literal["ephemeral", "event_log", "artifact_only"] = "event_log"

    data: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[str] = field(default_factory=list)
```

Use `seq` as the authoritative ordering field. Timestamps are useful, but sequence numbers are easier for replay, reconnect, and gap detection. OpenResponses uses `sequence_number` for stream ordering, and AG-UI/streaming protocols generally rely on ordered event sequences. ([Open Responses][1])

## Golden event taxonomy

Use dot-separated event names. Keep the taxonomy small, but reserve the right categories.

### Run and turn lifecycle

```text
run.started
run.completed
run.failed
run.cancelled

turn.started
turn.completed
turn.failed
turn.cancelled
turn.blocked
```

Rationale: Codex separates turn and thread/run semantics, and OpenAI Agents SDK warns that streamed runs are not complete until the stream finishes and post-processing can complete after the last visible token. ([OpenAI][2])

### Context and compaction

```text
context.built
context.truncated
context.resource.added
context.resource.updated
context.project_instructions.loaded

checkpoint.started
checkpoint.completed
checkpoint.failed

compaction.started
compaction.completed
compaction.failed
```

Rationale: context is now a managed runtime resource. MCP resources and resource-update notifications are the right reference for context/resource change events. ([Model Context Protocol][14])

### Model and provider stream

```text
model.request.started
model.stream.started
model.output_item.started
model.content_part.started
model.text.delta
model.content_part.completed
model.output_item.completed
model.completed
model.failed
model.usage
model.rate_limit
model.retry.scheduled
model.retry.started
model.retry.completed
```

Rationale: OpenResponses defines response lifecycle events, output items, content parts, output-text deltas, and response completion/failure. OpenAI’s API also exposes usage, service tier, incomplete reasons, and stream obfuscation options. ([Open Responses][1])

### Reasoning

```text
reasoning.started
reasoning.summary.delta
reasoning.visible.delta
reasoning.signature
reasoning.encrypted
reasoning.completed
reasoning.failed
```

Rationale: OpenResponses explicitly supports reasoning `content`, `encrypted_content`, and `summary`; OpenAI Responses exposes reasoning items with summaries and encrypted content. ([Open Responses][1])

### Tool calls

```text
tool.call.started
tool.args.delta
tool.args.completed
tool.policy.evaluated
tool.approval.requested
tool.approval.resolved
tool.execution.started
tool.output.delta
tool.execution.completed
tool.execution.failed
```

Rationale: OpenResponses has function-call argument deltas and externally/internally hosted tools; AG-UI and Vercel’s UI stream protocol also model tool input streaming and output availability. ([Open Responses][1])

### Shell and patch specializations

```text
command.started
command.stdout.delta
command.stderr.delta
command.completed
command.timeout
command.killed

patch.started
patch.applied
patch.failed
patch.rolled_back

diff.created
diff.updated
diff.finalized
```

Rationale: Tinyagent’s coding harness has domain-specific primitives that general-purpose protocols do not model well. Codex App Server also treats command execution, approvals, and diffs as richer harness-level items rather than plain model messages. ([OpenAI][2])

### State, UI, and activity

```text
state.snapshot
state.delta

activity.started
activity.delta
activity.completed
activity.failed
```

Rationale: AG-UI explicitly includes state management and activity categories; LangGraph distinguishes state updates, full state values, tokens, debug, and custom streams. ([AG-UI][3])

### Artifacts and sources

```text
artifact.created
artifact.updated
artifact.finalized
artifact.deleted

source.added
source.updated
citation.added
file.attached
```

Rationale: OpenResponses and Vercel AI SDK both include source/file concepts; A2A uses artifacts as task outputs. ([AI SDK][11])

### Human-in-the-loop and elicitation

```text
approval.requested
approval.resolved

elicitation.requested
elicitation.completed
elicitation.cancelled
elicitation.failed

interrupt.requested
interrupt.resolved
```

Rationale: Codex App Server supports approval pauses during a turn; MCP elicitation supports structured user input and URL-mode flows, with accept/decline/cancel semantics. ([OpenAI][2])

### Delegation and subagents

```text
handoff.requested
handoff.started
handoff.completed
handoff.failed

subagent.started
subagent.message
subagent.artifact.created
subagent.completed
subagent.failed
```

Rationale: OpenAI Agents SDK has handoff events, and A2A is explicitly about agent-to-agent collaboration, capability discovery, long-running tasks, messages, and artifacts. ([openai.github.io][12])

### Capabilities and configuration

```text
capabilities.discovered
capabilities.changed
tools.changed
resources.changed
workspace.changed
profile.changed
policy.changed
```

Rationale: MCP has list-changed notifications for tools, resources, prompts, and roots, and Codex has configuration/session concepts where reconfiguration can abort running execution. ([OpenTelemetry][7])

### Guardrails, safety, and telemetry

```text
guardrail.started
guardrail.passed
guardrail.failed

policy.violation
secret.redacted

telemetry.usage
telemetry.cost
telemetry.cache
telemetry.latency
```

Rationale: OpenTelemetry’s GenAI semantic conventions are the right reference for external observability spans/metrics, while Tinyagent should keep local operational events smaller and export to OpenTelemetry only when needed. ([OpenTelemetry][15])

## The minimum Tinyagent event set for now

Do not implement the entire taxonomy immediately.

The M1.7 runtime implements this durable set, plus live-only deltas marked below:

```text
run.started
run.completed
run.failed

context.built
compaction.started
checkpoint.completed

model.request.started
model.stream.started
model.completed
model.failed
model.usage
message.completed

tool.call.started
tool.args.completed
tool.policy.evaluated
tool.execution.started
tool.execution.completed
tool.execution.failed

shell.preflight.completed
files.listed
file.read
search.completed
command.started
command.completed
patch.applied
diff.finalized

artifact.created

live-only:
model.text.delta
reasoning.summary.delta
reasoning.encrypted
tool.args.delta
```

This is enough to handle:

```text
streaming text
streaming tool arguments
reasoning summaries/encrypted state
tool execution
durable artifacts
context checkpoints
final diff
```

Leave the rest as reserved event families.

## Provider-stream contract

Separate provider chunks from normalized events.

```python
@dataclass(frozen=True)
class ProviderStreamEvent:
    provider: str
    type: str
    raw: dict[str, Any]
    received_at: str
```

Then normalize into:

```python
@dataclass(frozen=True)
class ModelDelta:
    kind: Literal[
        "text_delta",
        "reasoning_summary_delta",
        "reasoning_visible_delta",
        "reasoning_encrypted",
        "tool_call_started",
        "tool_call_args_delta",
        "tool_call_completed",
        "output_item_started",
        "output_item_completed",
        "usage",
        "completed",
        "failed",
    ]
    item_id: str | None = None
    tool_call_id: str | None = None
    delta: str = ""
    data: dict[str, Any] = field(default_factory=dict)
```

Then assemble into the same final shape Tinyagent already uses:

```python
@dataclass
class AssembledModelResponse:
    content: str
    tool_calls: tuple[ToolCall, ...]
    reasoning_summary: str = ""
    reasoning_encrypted_artifact: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
```

Rule:

```text
Streaming and non-streaming must converge to the same final ModelResponse/ToolCall path before tool execution.
```

## Live stream contract

Expose live stream events through a sink interface:

```python
class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...
```

Implement sinks:

```text
NullSink           default
ConsoleTextSink    assistant text + simple tool status
JsonlStreamSink    normalized stream events to stdout
CompositeSink      fan-out
```

Do not make the kernel know about terminals, WebSockets, or UI frameworks.

## Durability policy

Not all events belong in `events.jsonl`.

Use this policy:

| Event kind            | Live stream |  Durable event |                  Artifact |
| --------------------- | ----------: | -------------: | ------------------------: |
| lifecycle             |         yes |            yes |                        no |
| text deltas           |         yes |  no by default |       optional raw stream |
| reasoning deltas      |    optional |  no by default | optional summary artifact |
| encrypted reasoning   |  no display | metadata event |        encrypted artifact |
| tool args deltas      |         yes |  no by default |      final assembled args |
| tool execution        |         yes |            yes |           output artifact |
| command output deltas |       later |  no by default |   command output artifact |
| context built         |         yes |            yes |          context artifact |
| checkpoint            |         yes |            yes |       checkpoint artifact |
| final diff            |         yes |            yes |                final.diff |
| telemetry cost/usage  |         yes |            yes |              metrics.json |

This keeps traces compact.

## External protocol adapters

Use these mappings:

```text
Tinyagent internal stream -> AG-UI:
  run.*                 -> RUN_STARTED / RUN_FINISHED / RUN_ERROR
  model.text.delta      -> TEXT_MESSAGE_CONTENT
  tool.*                -> TOOL_CALL_START / TOOL_CALL_ARGS / TOOL_CALL_END
  state.*               -> STATE_SNAPSHOT / STATE_DELTA
  reasoning.*           -> AG-UI reasoning events
  custom/internal       -> CUSTOM

Tinyagent tools/resources -> MCP:
  Tool definitions      -> tools/list
  Tool execution        -> tools/call
  Artifacts/resources   -> resources/read or resource_link
  User prompts          -> prompts/list/get
  Human input           -> elicitation/create

Tinyagent delegation -> A2A:
  subagent/handoff      -> A2A task/message/artifact
  artifact.created      -> A2A artifact

Tinyagent telemetry -> OpenTelemetry:
  model call            -> gen_ai inference span
  tool call             -> tool execution span
  run/turn              -> agent span
  usage/cost            -> gen_ai metrics
```

This is the cleanest way to stay interoperable without sacrificing Tinyagent’s own shape.

## Concrete next implementation

M1.7 keeps the runtime primitives in small modules:

```text
agentd/events.py        Event, sinks, event taxonomy, json safety
agentd/model_stream.py  ModelDelta, ProviderStreamEvent, assembler, stream parsing
agentd/providers/       provider adapters
```

Use the protocol taxonomy directly:

```text
Event is both the durable JSONL envelope and the normalized live stream envelope.
Durability and visibility are Event fields.
Live-only deltas must stay out of durable events unless explicitly promoted.
```

The durable runtime should use dot-named protocol events directly:

```text
run.started
context.built
model.request.started
model.completed
tool.call.started
tool.args.completed
tool.execution.started
tool.execution.completed / tool.execution.failed
command.started
command.completed
patch.applied
diff.finalized
artifact.created
```

## Final opinion

The “golden setup” is:

```text
1. Internal item/event protocol inspired by OpenResponses + Codex.
2. Dot-named normalized event taxonomy.
3. Items as state machines.
4. Events as item state transitions/deltas.
5. Artifacts for large payloads.
6. Provider chunks normalized before entering the harness.
7. AG-UI/MCP/A2A/OpenTelemetry as adapters, not as the core.
```

The most important architectural sentence:

```text
Tinyagent should not be an OpenResponses clone, an AG-UI server, an MCP host, or an A2A agent by default.
Tinyagent should be a tiny agent VM whose internal item/event model can losslessly adapt to those protocols.
```

That gives us the flexibility to become the best harness without inheriting any one ecosystem’s complexity.

[1]: https://www.openresponses.org/specification "Specification"
[2]: https://openai.com/index/unlocking-the-codex-harness/ "Unlocking the Codex harness: how we built the App Server | OpenAI"
[3]: https://docs.ag-ui.com/concepts/events "Events - Agent User Interaction Protocol"
[4]: https://docs.ag-ui.com/introduction "AG-UI Overview - Agent User Interaction Protocol"
[5]: https://tanstack.com/ai/latest/docs/protocol/chunk-definitions "AG-UI Event Definitions | TanStack AI Docs"
[6]: https://modelcontextprotocol.io/specification/2025-11-25 "Specification - Model Context Protocol"
[7]: https://opentelemetry.io/docs/specs/semconv/gen-ai/mcp/?utm_source=chatgpt.com "Semantic conventions for Model Context Protocol (MCP)"
[8]: https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation "Elicitation - Model Context Protocol"
[9]: https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/ "
            
            Announcing the Agent2Agent Protocol (A2A)
            
            
            \- Google Developers Blog
            
        "
[10]: https://docs.langchain.com/langgraph-platform/streaming "Streaming API - Docs by LangChain"
[11]: https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol "AI SDK UI: Stream Protocols"
[12]: https://openai.github.io/openai-agents-python/streaming/ "Streaming - OpenAI Agents SDK"
[13]: https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md?utm_source=chatgpt.com "spec/cloudevents/spec.md at main"
[14]: https://modelcontextprotocol.io/specification/2025-11-25/server/resources "Resources - Model Context Protocol"
[15]: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-events/?utm_source=chatgpt.com "Semantic conventions for Generative AI events"
