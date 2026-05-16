# Provider Adapter Refactor Goal

## Mini Goal

Make the OpenAI/Codex path behave like a serious Responses API coding-agent
transport without making tinyagent an OpenAI-specific harness.

Small version:

```text
Make every provider adapter speak its own native protocol at the edge while the
kernel only sees tinyagent's normalized agent contract.
```

In concrete terms: keep the kernel provider-neutral, move provider-specific
wire-format behavior into adapters, add traceable capability flags, allow
parallel-safe tool batches, and prove the result with the same coding stress
eval across OpenAI Responses, Codex subscription Responses, OpenAI-compatible
Chat Completions, and at least one local OpenAI-compatible backend.

The mini-goal is deliberately narrow. It is not "support every provider." It is
"make the boundary true." Once the boundary is true, adding providers becomes
normal adapter work instead of a kernel refactor each time.

## Current Implementation Status

This document is both the implementation goal and the refactor map. It keeps
the original evidence because that evidence explains why the refactor exists,
but several first slices may already be underway in the working tree:

- budget naming should converge on `max_model_calls`;
- provider capabilities should converge on explicit protocol/capability fields;
- Responses adapters should record provider conversation state and cache keys;
- tool metadata should describe parallel-safety without changing dispatch
  behavior until tests prove it safe.

Treat completed items in this file as exit checks, not as reasons to preserve
legacy names. If a slice has already landed, the next implementation step is the
smallest adjacent slice that removes another provider leak or improves evidence.

Implemented slices in the current working tree:

- `max_turns` has been renamed to `max_model_calls` in runtime config and tests.
- provider capabilities now expose protocol and Responses-specific affordances.
- OpenAI Responses records prompt cache keys and provider conversation state.
- OpenAI Responses requests `parallel_tool_calls` by default.
- tool runtime metadata is visible in logical request artifacts.
- the kernel can concurrently execute a narrow batch of consecutive
  `parallel_safe` local tools while preserving model-visible result order.
- profiles add short parallel-exploration guidance only when the selected model
  and visible tools can support it.
- a native Anthropic Messages adapter exists with fixture coverage for tool
  schemas, `tool_use` parsing, and `tool_result` history mapping.
- a partial `open-responses` provider kind exists for stateless
  Responses-compatible servers; it reuses Responses item parsing but does not
  send OpenAI-only state/cache fields by default.
- a native Gemini GenerateContent adapter exists with fixture coverage for
  function declarations, `functionCall` parsing, `functionResponse` history,
  usage mapping, and thought-signature preservation on tool calls.
- non-streaming model responses with normalized `raw["usage"]` now emit a
  `model.usage` event, so usage is visible consistently in traces even when a
  provider does not stream.
- gated live smoke coverage exists for native provider kinds
  `openai-responses`, `open-responses`, `anthropic`, and `gemini`; these tests
  stay skipped by default and run only when a matching live provider is selected
  through integration env vars.
- eval results now include observed provider, model, protocol, adapter,
  provider-reported token usage, cached-token counts, reasoning-token counts,
  and safe parallel batch counts so provider variants can be compared on
  adapter fidelity, not only solve rate.
- all model providers now receive `ModelRequestContext`, a small
  provider-facing snapshot of run id, recent tool history, checkpoint offset,
  and provider conversation state, instead of receiving the full mutable
  `RunState`.

## Learned Diagnosis

This section captures the practical learning from comparing tinyagent's current
behavior with Codex-style, Hermes-style, and Pi-style harnesses.

The important conclusion is:

```text
One model request per model decision is not the bug.
Unnecessary serialized model decisions are the bug.
```

Modern tool-using models normally work as a loop:

1. send prompt/history/tools to the model;
2. receive text and/or tool calls;
3. execute the requested tools;
4. send tool results back;
5. continue until done.

That loop is fine. The suspicious behavior in the coding example was not that
the harness used the Responses API for each model decision. The suspicious
behavior was that the model burned too many model decisions on reads that were
knowable at the same time.

The coding example did not look complicated enough to require more than 35
tool calls. That can mean a few different things:

- The model may only be seeing small chunks, so it keeps asking for adjacent
  context.
- The prompt may fail to tell it to batch independent exploration.
- The provider adapter may disable native parallel tool calls.
- The kernel may serialize safe calls even when the model returns a batch.
- Tool output may be truncated in confusing units, especially when the code
  talks about characters while everyone reasons about tokens.
- The model-call budget may feel like a "turn" budget even though a provider
  request is not the same conceptual thing as a user/assistant turn.
- The adapter may not use provider cache/state affordances, so repeated context
  becomes expensive even when behavior is otherwise correct.

The first actual traces suggested the model was not broken. It searched, read,
edited, tested, and inspected diffs in a recognizable coding-agent workflow.
The issue was efficiency and harness affordance, not total incompetence.

That matters for the refactor because it points to a specific fix:

```text
Do not invent a new planner.
Make the provider boundary honest, enable native tool batching where supported,
make safe local batches executable, use token-based budgets, and measure the
same coding task before and after.
```

## Harness Comparison Takeaways

The comparison should influence tinyagent without turning tinyagent into a
clone of another harness.

### Codex Harness

Codex is the strongest reference for the OpenAI/Codex adapter because it is
already optimized around the Responses API family.

Useful behaviors to copy:

- treat Responses as a first-class protocol, not Chat Completions with a
  different URL;
- pass `parallel_tool_calls` through when the model/profile supports it;
- use a stable prompt cache key tied to the conversation/thread identity;
- keep function calls before function call outputs in the model-visible
  history;
- give the model explicit instructions to batch independent reads;
- preserve enough provider state to make traces and continuation behavior
  understandable;
- keep policy/sandbox decisions outside the provider transport.

Things not to copy blindly:

- Codex-specific auth paths into the kernel;
- assumptions that every Responses-family server has OpenAI feature parity;
- Codex product concepts that do not exist in tinyagent;
- opaque provider state without trace artifacts.

### Hermes-Style Agents

Hermes-like harnesses often feel strong because they allow a coding loop to run
long enough and because their tool surfaces are direct. The lesson is not that
tinyagent needs no budget. The lesson is that a budget must be named and
calibrated honestly.

Tinyagent should keep a model-call budget, but it should be understood as:

```text
maximum provider model decisions for a run
```

not "turns." A human turn, a provider request, and a tool execution batch are
different units. Confusing those units creates false conclusions about whether
the model is looping badly.

### Pi-Style Agents

Pi-style harnesses are useful as a reminder that the kernel should remain a
small runtime around tools, state, policy, and events. Provider details should
adapt to that runtime. The runtime should not absorb OpenAI-specific,
Anthropic-specific, or Gemini-specific concepts just because one provider needs
them.

The design rule is:

```text
The adapter modifies itself to fit the harness. The harness does not become a
different harness for every adapter.
```

If a provider need reveals a real missing kernel primitive, add the smallest
provider-neutral primitive and prove that at least two adapters can use it.
Otherwise keep the change inside the adapter.

## Refactor Goal In One Paragraph

The refactor should leave tinyagent with a small, provider-neutral kernel and a
set of explicit adapters. The kernel owns model-call budgeting, normalized
messages, normalized tool calls, tool results, policy checks, workspace
effects, events, artifacts, and replay. Each adapter owns the provider wire
format, request fields, response parsing, streaming events, usage extraction,
reasoning/state/cache handles, and compatibility quirks. The OpenAI/Codex
adapter should become excellent first because it has the clearest evidence and
the strongest current user need, but it must not set the shape of the kernel.
Anthropic, Gemini, Open Responses, and OpenAI-compatible Chat Completions should
all map into the same tinyagent contract.

## Full Goal

Refactor tinyagent's model-provider layer into a lean adapter system that can
support multiple modern agent protocols without leaking any provider's wire
format into the kernel.

The end state should satisfy these constraints:

1. The kernel owns only the normalized agent contract: messages, tool calls,
   tool results, model responses, events, artifacts, policy decisions, budgets,
   and workspace mutations.
2. Adapters own provider wire formats, request shaping, streaming parsers,
   provider state handles, cache knobs, reasoning replay, and protocol quirks.
3. The default OpenAI/Codex Responses adapter should follow the Codex harness
   shape closely where that shape is clearly beneficial: Responses transport,
   `parallel_tool_calls`, prompt cache keying, streaming item parsing, reasoning
   replay where applicable, and model-visible instructions that encourage
   batched exploration.
4. The broad compatibility path should remain OpenAI-compatible Chat
   Completions because most local servers and third-party gateways still expose
   that shape.
5. Open Responses should be supported as an adapter family or compatibility
   target, not treated as identical to OpenAI Responses. Some implementations
   support only a subset, and the harness must discover or configure that
   subset explicitly.
6. Native provider protocols such as Anthropic Messages and Gemini
   GenerateContent should map into the same internal contract rather than
   forcing those providers through an OpenAI-shaped mental model.
7. Safety and policy modes must remain orthogonal to provider transport.
   `yolo`, approval, and auto-review should be policy hooks around tool
   execution, not model-provider features.
8. The refactor should delete or collapse special cases where possible. If a
   new abstraction does not remove complexity, make traces clearer, or support a
   real adapter need, it should not exist.

The goal is not to create a provider framework. The goal is to make the current
provider boundary honest, testable, and capable enough that adding one provider
does not distort the kernel.

## Why This Matters

The OpenAI/Codex coding stress run succeeded, but the trace showed a real
efficiency problem.

Observed run shape:

- 25 model calls.
- 24 tool calls.
- 0 tool errors.
- 0 policy denials.
- 0 compactions.
- Validation passed.
- The model inspected before editing and verified after editing.
- Actual provider usage across response artifacts was about 358k input tokens,
  6.2k output tokens, 1.9k reasoning tokens, and 0 cached input tokens.

That means the harness worked, but the OpenAI/Codex adapter left important
provider capabilities unused.

The model was not obviously confused. It did not keep reading the same file
again and again. It serialized a reasonable workflow:

1. Search the repo.
2. Read the implementation brief.
3. Read source modules.
4. Read tests, fixtures, README, and architecture docs.
5. Patch multiple files.
6. Read status and diff.
7. Patch docs.
8. Run tests.
9. Run validation.
10. Inspect final diff.
11. Finish.

The concerning part is that many of those reads were predictable after the
initial search. A stronger harness/model contract should allow the model to
batch independent reads and the kernel to execute safe read-only tools in
parallel. Codex explicitly does this by enabling parallel tool calls and
prompting the model to batch exploration. Hermes and similar harnesses also
allow larger iteration budgets and parallel-safe dispatch, which explains why
they feel less boxed in during codebase navigation.

So the main finding is:

```text
The issue is not that every tool cycle is a Responses API request.
The issue is that tinyagent currently turns each predictable tool read into a
separate request and does not use provider cache/state affordances.
```

## Current Repo Evidence

The current code already has the most important foundation: the kernel is not
hardwired to a single model wire format.

Important existing surfaces:

- `tinyagent/core/state.py`
  - `Message`
  - `ToolCall`
  - `ToolResult`
  - `ToolStep`
  - `ModelResponse`
  - `RunBudgets`

- `tinyagent/core/models.py`
  - `ModelCapabilities`
  - `ModelSpec`
  - `model_capabilities`
  - `model_spec`

- `tinyagent/core/kernel.py`
  - calls a model provider
  - records the model response
  - iterates through all returned tool calls
  - dispatches tools
  - records events, artifacts, policy, and final output

- `tinyagent/core/providers/openai_compat.py`
  - OpenAI-compatible Chat Completions adapter

- `tinyagent/core/providers/openai_responses.py`
  - OpenAI Responses and Codex subscription-backed Responses adapter

- `tinyagent/core/model_stream.py`
  - normalized streaming assembly

The weak points observed at the start of this refactor were also clear:

- `ModelCapabilities.tool_protocol` is too shallow. It can say
  `chat_completions`, `responses`, or `none`, but it cannot express the real
  compatibility surface.
- `OpenAIResponsesProvider` currently sets `supports_parallel_tools=False`.
- `OpenAIResponsesProvider.build_payload` hardcodes `parallel_tool_calls=False`.
- The Responses adapter sends `store=False`, but does not use a
  `prompt_cache_key`, `previous_response_id`, `conversation`, or an explicit
  stateless reasoning replay strategy.
- `RunBudgets.max_turns` is really a model-call budget in the kernel. It should
  become `max_model_calls`, since a "turn" in tinyagent is not the same as a
  provider request.
- Tool execution is sequential even when the model returns a batch of read-only
  calls that could be safely executed together.
- Tests assert the current low-fidelity behavior, including
  `parallel_tool_calls: false`, so refactoring requires changing the tests as
  part of the design, not just changing code.

## Protocol Landscape

The adapter plan should be based on current protocol reality, not a preference
for one shape.

### OpenAI Responses

Use this as the highest-fidelity reference path for OpenAI and Codex.

Important features:

- `/v1/responses`.
- Structured output items, including function calls.
- Built-in tools.
- Streaming events.
- `parallel_tool_calls`.
- `prompt_cache_key`.
- `previous_response_id`.
- `conversation`.
- `include` options such as reasoning encrypted content for stateless
  multi-turn reasoning replay where supported.
- Provider-specific features such as service tier, text verbosity, reasoning
  config, and model phases.

Tinyagent does not need every feature immediately. It does need a capability
model rich enough to represent which of these are enabled, unsupported, or
deliberately disabled.

### Codex Subscription Responses

This is not a separate internal protocol. It is an OpenAI Responses-family
adapter with different auth, endpoint, and payload quirks.

Existing learning:

- Codex subscription auth should be verified through tinyagent's own provider
  path, not by proving the Codex CLI works.
- The Codex endpoint did not accept `max_output_tokens` in the same way as the
  standard OpenAI Responses endpoint, so the adapter already has a
  provider-specific send flag.
- Codex harness source shows `parallel_tool_calls` is passed through from the
  prompt and `prompt_cache_key` is set from a thread id.
- Codex prompting guidance says parallel tool calling works better when the
  model is explicitly instructed to plan all needed reads, batch them, and keep
  function calls before function call outputs.

This gives us a concrete reference for the first serious adapter target.

### OpenAI-Compatible Chat Completions

This is still the broadest compatibility baseline.

Most local servers and third-party gateways expose some flavor of:

```text
POST /v1/chat/completions
```

with messages, tools, tool calls, and tool result messages. Compatibility varies
widely. Some servers support tools well, some only claim compatibility, and some
need specific chat templates to emit structured tool calls.

Tinyagent should keep this path because it is the easiest way to support local
models, vLLM-style servers, llama.cpp-style servers, OpenRouter-style gateways,
and other provider routers. But this path should not dictate the internal
contract.

### Open Responses

Open Responses is an open multi-provider specification and ecosystem based on
the OpenAI Responses shape. It is promising because it tries to standardize the
agentic pieces that Chat Completions handles awkwardly: items, tool use,
streaming events, and multi-provider interoperability.

But it should be treated as a compatibility target, not as an assumption that
every `/responses` server behaves like OpenAI.

Example: Ollama documents support for `/v1/responses`, but only the non-stateful
flavor. That means no `previous_response_id` or `conversation` support there.

Therefore:

```text
Responses-family adapter != OpenAI Responses feature parity.
```

The right design is capability probing or explicit provider capability config.

### Anthropic Messages

Anthropic uses a different native shape:

- request-level `tools`;
- model returns `tool_use` content blocks;
- caller returns `tool_result` content blocks;
- optional fine-grained tool streaming and provider-specific thinking/tool
  behavior.

Forcing Anthropic into Chat Completions or OpenAI Responses internally would
hide important semantics. A native adapter should translate Anthropic blocks
into tinyagent's normalized `ToolCall` and `ToolResult` objects.

### Gemini GenerateContent

Gemini uses:

- `tools` with `functionDeclarations`;
- response `functionCall` parts;
- follow-up `functionResponse` parts;
- provider-specific thought signatures and thinking configuration for some
  model families.

Again, the internal contract should remain normalized. The Gemini adapter should
handle Gemini-specific request history, function ids, thought signatures, and
stream parsing without changing the kernel.

## Design Stance

The refactor should use one internal protocol and many wire adapters.

The internal protocol is not OpenAI Responses. It is not Chat Completions. It is
the tinyagent runtime contract:

```text
RunState
Message
ModelRequestSnapshot
ModelResponse
ToolCall
ToolResult
ToolStep
Event
Artifact
PolicyDecision
WorkspaceDelta
```

Provider adapters map between this contract and the outside world.

This is the critical boundary:

```text
kernel -> normalized request -> adapter -> provider wire request
provider wire response -> adapter -> normalized response -> kernel
```

The kernel should not know whether the provider used:

- `input` items;
- chat messages;
- Anthropic content blocks;
- Gemini parts;
- `previous_response_id`;
- a conversation id;
- encrypted reasoning items;
- provider-specific response ids;
- prompt cache keys;
- a compatibility gateway.

The kernel should know only:

- what the model said;
- what tool calls the model requested;
- whether the provider response had usage;
- whether a provider state handle should be retained;
- what normalized events/artifacts should be recorded.

## Refactor Principles

Use these as hard review rules.

1. No provider lock-in.
   - Provider-specific fields must not leak into the kernel's control flow.

2. Capabilities over conditionals.
   - Prefer a capability object over `if provider == "openai-codex"` scattered
     around runtime code.

3. Artifacts over hidden state.
   - Exact provider payloads, normalized requests, normalized responses, and
     parsed provider state should be recorded as artifacts or small events.

4. Token units, not characters.
   - Budgets and truncation knobs should use token naming and token estimates.

5. Delete compatibility shims once migrated.
   - The repo is not used by external users yet. Do not preserve confusing old
     names or legacy code paths out of habit.

6. Keep the kernel boring.
   - Parallel dispatch, budget checks, and event recording are kernel-adjacent.
     Provider request fields are not.

7. Safety is not a provider feature.
   - `yolo`, approval, and auto-review must be policy/execution hooks. Providers
     can influence tool formatting but must not own safety semantics.

8. Tests should pin behavior, not implementation nostalgia.
   - If a current test asserts an intentionally weak adapter behavior, update
     the test as part of the refactor.

## Target Internal Contract

The existing structures are close. The refactor should make the provider
boundary more explicit rather than adding a large framework.

### ModelRequestContext

Use a normalized provider-facing request context at the adapter boundary. This
is not a second runtime state object. It is the smallest snapshot adapters need
to shape native provider history and cache/state fields without reaching into
the mutable kernel state.

Current shape:

```python
@dataclass(frozen=True)
class ModelRequestContext:
    run_id: str
    tool_steps: tuple[ToolStep, ...]
    context_checkpoint_tool_step_count: int
    conversation_state: ModelConversationState | None

    def tool_steps_since_checkpoint(self) -> tuple[ToolStep, ...]: ...
```

The kernel still calls providers through the simple
`complete(messages, tools, request)` shape, but `request` is always
`ModelRequestContext`. There is no provider opt-in flag and no `RunState`
fallback at the model-provider boundary.

### ModelConversationState

Adapters need a place to store provider state handles without contaminating the
kernel.

Sketch:

```python
@dataclass(frozen=True)
class ModelConversationState:
    provider: str
    adapter: str
    response_id: str | None = None
    conversation_id: str | None = None
    prompt_cache_key: str | None = None
    reasoning_items: tuple[dict[str, Any], ...] = ()
    opaque: Mapping[str, Any] = field(default_factory=dict)
```

This is adapter-owned metadata. The kernel stores and replays it, but should not
interpret provider-specific `opaque` contents.

### ModelResponse

`ModelResponse` should remain the normalized output.

It may need additional optional metadata:

```python
provider_state: ModelConversationState | None
usage: ModelUsage | None
raw_artifact: str | None
```

Do not put huge raw payloads in `ModelResponse`. Keep raw payloads in artifacts.

### ModelUsage

Provider usage should be normalized enough for evals:

```python
input_tokens
cached_input_tokens
output_tokens
reasoning_tokens
total_tokens
```

Unknown values should be `None` or `0` consistently. Evals should clearly
distinguish "provider did not report" from "provider reported zero".

### ModelCapabilities

Replace the current shallow shape with a richer but still small capability
object.

Candidate fields:

```python
protocol: Literal[
    "openai_chat_completions",
    "openai_responses",
    "open_responses",
    "anthropic_messages",
    "gemini_generate_content",
    "none",
]
supports_tools: bool
supports_parallel_tool_calls: bool
supports_streaming: bool
supports_streaming_tool_deltas: bool
supports_prompt_cache_key: bool
supports_stateful_responses: bool
supports_conversation_resource: bool
supports_reasoning: bool
supports_reasoning_replay: bool
supports_builtin_tools: bool
supports_strict_tool_schema: bool
supports_json_schema_output: bool
tool_result_mode: Literal["responses_items", "chat_tool_messages", "anthropic_blocks", "gemini_parts"]
max_tool_calls_per_response: int | None
```

Keep this list honest. Add fields only when code or tests use them.

## Target Adapter Set

### Adapter 1: OpenAI Responses

Purpose:

- High-fidelity OpenAI API path.
- Reference adapter for modern agentic workflows.

Must support:

- standard API key auth;
- `/v1/responses`;
- streaming and non-streaming parsing;
- function calls;
- multiple function calls per response;
- `parallel_tool_calls` when configured;
- `prompt_cache_key` when configured;
- `store=false` stateless mode;
- optional `previous_response_id` or `conversation` mode;
- reasoning config and reasoning replay include where applicable;
- usage extraction;
- exact request and response artifacts.

Default behavior should probably remain privacy-conservative:

```text
store=false
state_mode=stateless_replay
prompt_cache_key=stable thread/run key if provider supports it
parallel_tool_calls=true only after kernel can safely dispatch read-only batches
```

The important detail is that `store=false` should not mean "ignore every other
efficiency feature."

### Adapter 2: OpenAI Codex Responses

Purpose:

- Use the user's existing Codex/ChatGPT subscription auth path.
- Stay as close as possible to the Codex harness request shape where tinyagent
  can support it.

Differences from standard OpenAI Responses:

- auth token comes from Codex login;
- default base URL differs;
- some payload fields may need to be omitted;
- model naming may differ;
- state/cache behavior should be verified empirically.

Must not:

- make Codex CLI the execution surface;
- put Codex-specific behavior in the kernel;
- silently diverge from OpenAI Responses without a capability or config flag.

### Adapter 3: OpenAI-Compatible Chat Completions

Purpose:

- Broad provider/local-model compatibility.

Must support:

- `/v1/chat/completions`;
- messages;
- `tools`;
- assistant `tool_calls`;
- tool result messages;
- streaming where robust;
- provider-specific fallbacks for servers that do not support strict schemas.

Should not pretend:

- that every OpenAI-compatible server supports tools reliably;
- that local models will emit valid tool JSON without the right prompt/template;
- that Chat Completions can express every Responses feature.

This adapter should be the compatibility workhorse, not the architecture
template.

### Adapter 4: Open Responses

Purpose:

- Support providers/gateways that implement the Open Responses spec.

Must support:

- explicit capability declaration or probing;
- non-stateful `/v1/responses` servers;
- partial compatibility;
- acceptance-test fixtures if the provider/spec exposes them.

Must not assume:

- `previous_response_id`;
- `conversation`;
- reasoning encrypted content;
- built-in tools;
- exact OpenAI event names;
- exact OpenAI usage fields.

### Adapter 5: Anthropic Messages

Purpose:

- Native Claude support without going through a lossy compatibility layer.

Must map:

- tinyagent tools -> Anthropic `tools`;
- Anthropic `tool_use` blocks -> `ToolCall`;
- `ToolResult` -> `tool_result` blocks;
- usage -> `ModelUsage`;
- content blocks -> normalized assistant text.

Later support:

- fine-grained tool streaming;
- prompt caching headers/blocks;
- thinking/reasoning metadata if exposed;
- server-side tools if they become relevant.

### Adapter 6: Gemini GenerateContent

Purpose:

- Native Gemini support.

Must map:

- tinyagent tools -> Gemini `functionDeclarations`;
- Gemini `functionCall` parts -> `ToolCall`;
- `ToolResult` -> `functionResponse` parts;
- thought signatures or equivalent continuity handles where required;
- usage -> `ModelUsage`;
- content parts -> normalized assistant text.

Later support:

- model-specific thinking config;
- multimodal function responses;
- compositional function calling.

## Parallel Tool Calls

Parallel tool calls need two separate pieces:

1. The provider request may allow the model to emit multiple independent tool
   calls in one response.
2. The kernel may execute some returned calls concurrently.

These are related but not identical.

The first piece is adapter capability:

```text
supports_parallel_tool_calls
```

The second piece is tool safety metadata:

```text
tool.parallel_safe
tool.mutation_scope
tool.requires_workspace_write_lock
tool.requires_shell_lock
tool.network_mode
```

The kernel should be conservative:

- Read-only file reads can run in parallel.
- Search calls can run in parallel.
- Context reads can run in parallel.
- Independent artifact reads can run in parallel.
- Shell should default to sequential.
- Apply patch should be sequential.
- Workspace-mutating tools should take a write lock.
- Policy/approval checks must still happen per tool call.

This gives us Codex-like exploration speed without losing traceability.

The event log should make parallel batches explicit:

```text
tool.batch.started
tool.execution.started
tool.execution.completed
tool.execution.completed
tool.batch.completed
```

If we do not want new event types yet, we can record `batch_id` on existing tool
events. Prefer the smaller change unless surfaces need explicit batch events.

## Budget Naming Refactor

The current `max_turns` name is misleading. The kernel checks it against
`state.model_call_count`.

Change:

```text
max_turns -> max_model_calls
```

No backward compatibility is needed right now. Remove the old name from configs,
docs, tests, and examples.

Keep separate budgets:

```text
max_model_calls
max_tool_calls
max_run_seconds
max_model_timeout_seconds
max_model_idle_timeout_seconds
max_tool_output_tokens_visible
```

This helps because Hermes/Codex comparisons are otherwise confusing:

- A user thinks "turn" means conversation turn.
- The harness means "provider call."
- The model/tool loop may need many provider calls during one user turn.

Use token units everywhere for context and output budgets.

## Context and Tool Output Readability

The coding stress run was expensive partly because the model had to keep asking
for obvious files one at a time.

Fixing provider parallelism helps, but we should also tighten what the model
sees.

Keep these rules:

- Tool outputs should be bounded in tokens, not characters.
- Large outputs should become artifacts with summaries.
- `ContextFS` should keep refs stable and readable.
- After `apply_patch`, the model should trust the patch result unless there is a
  reason to verify the file.
- The model should be instructed to batch known reads when the adapter and tools
  support it.
- The model should not see every provider payload by default.

Do not make a large context framework. The current ContextFS direction is right:
events contain metadata, artifacts contain payloads, profile context contains
excerpts.

## Policy Hook Boundary

Policy must sit around tool execution and workspace effects.

Target modes:

```text
yolo
approval
autoreview
```

Mode meanings:

- `yolo`: no enforceable policy gate before execution. Still record events and
  workspace effects. "YOLO" should mean YOLO.
- `approval`: deterministic policy can require user approval before execution.
- `autoreview`: policy asks a small/cheap selected reviewer model whether a
  review or denial is needed.

Autoreview model selection should be configurable:

- default: selected run model if no explicit review model is configured;
- optional config: smaller/cheaper model for review;
- provider-neutral: review model can come from any provider adapter.

This policy work is adjacent to provider refactor but should not be bundled into
the same patch unless needed. The key adapter requirement is that policy should
not depend on the model transport.

## Implementation Map

Read this map as a refactor path, not as a project plan for a large framework.
Each phase should either remove a provider leak, improve protocol fidelity, or
produce evidence. If a phase does none of those, skip it.

The current working tree already contains the first meaningful slices:

- model-call budget naming;
- richer provider capability fields;
- OpenAI Responses cache/state fields;
- safe local batch dispatch for a narrow class of tools;
- model-visible parallel exploration guidance;
- a first native Anthropic Messages adapter proof.

That changes the remaining critical path. The next work should focus on
finishing the boundary, proving it across protocols, then deleting old
compatibility clutter.

### Current Critical Path

#### Track A: Finish The Normalized Boundary

Goal:

Make it obvious where normalized tinyagent state ends and provider wire format
begins.

Implementation work:

1. Audit provider adapters for direct `RunState` knowledge.
2. Keep only normalized inputs at the adapter boundary:
   - messages;
   - tool definitions;
   - tool steps/results;
   - provider conversation state;
   - run metadata needed for cache keys and trace labels.
3. Ensure provider request payloads are built inside adapters.
4. Ensure provider response parsing returns only normalized model responses and
   provider state updates.
5. Ensure raw provider payloads are artifact data, not kernel event data.
6. Search for provider names in kernel/runtime code and justify every hit.
7. Delete adapter-specific branches from the kernel unless the branch is really
   about normalized capability flags.

Exit checks:

- `tinyagent/core/kernel.py` does not branch on `openai`, `codex`,
  `anthropic`, `gemini`, or `responses` provider strings.
- Provider-specific request fields appear only under provider modules or tests.
- A reader can trace one model cycle as:

```text
kernel normalized request -> adapter payload -> provider raw response ->
adapter normalized response -> kernel tool/policy loop
```

#### Track B: Make OpenAI/Codex Responses Excellent

Goal:

The OpenAI subscription and OpenAI API path should be the best-supported
high-fidelity coding-agent transport, while still being one adapter family.

Implementation work:

1. Keep `parallel_tool_calls` enabled by default only when the kernel and
   visible tools can handle safe batches.
2. Keep `prompt_cache_key` stable and traceable.
3. Decide the first supported state mode:
   - keep `stateless_replay` as default;
   - add `previous_response_id` only if live evidence shows it works cleanly
     with replay/privacy expectations;
   - add `conversation` only when it has a real use case.
4. Add exact request fixture tests for both standard OpenAI Responses and Codex
   subscription Responses.
5. Add a fixture showing multiple function-call output items in one response.
6. Add a fixture showing the next request includes tool outputs in the correct
   provider-native order.
7. Confirm which payload fields the Codex subscription endpoint rejects and
   encode that as adapter config, not ad hoc conditionals.
8. Run the same coding stress example before and after each material adapter
   change.

Exit checks:

- Request fixtures show `parallel_tool_calls`, cache key, tool schema, and
  tool-result history explicitly.
- Codex subscription quirks are named in config/capabilities.
- The coding stress report can explain model-call count, tool-call count,
  parallel batch count, cached tokens, and validation result.

#### Track C: Keep Chat Compatibility Broad But Honest

Goal:

OpenAI-compatible Chat Completions remains the fallback path for local models,
gateways, and servers that do not support native Responses or native provider
protocols.

Implementation work:

1. Keep a separate `openai-compatible` adapter.
2. Do not force Chat Completions to pretend it supports Responses-only state.
3. Add clear provider errors for invalid tool JSON, missing tool ids, and
   servers that ignore `tools`.
4. Keep local-model prompt guidance direct and short.
5. Add gated live tests for the user's local OpenAI-compatible backend where
   practical.
6. Record provider capability assumptions in the run artifact.

Exit checks:

- A local model failure explains the provider compatibility issue rather than
  surfacing a Python traceback.
- The adapter can run with tools off or tools on, based on capability.
- The Chat path does not influence the native Responses, Anthropic, or Gemini
  contract.

#### Track C2: Keep Open Responses Partial By Default

Goal:

Support Responses-compatible servers without pretending they implement the full
OpenAI Responses API.

Implementation work:

1. Register an `open-responses` provider kind.
2. Require an explicit `TINYAGENT_MODEL_BASE_URL` so the provider cannot
   accidentally target OpenAI's hosted Responses endpoint.
3. Allow local servers without an API key by omitting the Authorization header
   when no key is configured.
4. Reuse Responses item parsing, tool schemas, and tool-result history mapping.
5. Do not send OpenAI-only state/cache fields by default:
   - `store`;
   - `prompt_cache_key`;
   - `previous_response_id`;
   - `conversation`.
6. Reject stateful fields clearly while the adapter is stateless.
7. Advertise `protocol="open_responses"` and
   `supports_stateful_responses=False`.

Exit checks:

- The request fixture contains only the common stateless Responses shape.
- The provider factory can create `open-responses`.
- The adapter can be extended later for stateful Open Responses without
  changing the kernel.

#### Track D: Prove Native Non-OpenAI Protocols

Goal:

Show that the kernel contract is not secretly OpenAI-shaped.

Implementation work:

1. Finish Anthropic Messages fixture coverage:
   - text-only response;
   - one `tool_use`;
   - multiple `tool_use` blocks;
   - `tool_result` history;
   - malformed tool args;
   - usage extraction.
2. Add one gated Anthropic live smoke test if credentials exist.
3. Add Gemini fixture adapter after Anthropic:
   - function declarations;
   - `functionCall` parsing;
   - `functionResponse` history;
   - usage extraction;
   - thought signature preservation if needed.
4. Make both adapters use the same normalized `ToolCall` and `ToolResult`
   objects as OpenAI/Codex.

Exit checks:

- Anthropic and Gemini fixture tests pass without changing kernel code.
- If a kernel change is needed, it is named as a provider-neutral primitive and
  justified against more than one adapter.

Current implementation note:

Gemini required a tiny provider-neutral extension to `ToolCall`: optional
metadata. The immediate use is carrying Gemini `thoughtSignature` data back into
the next native `functionCall` part while keeping tool args clean and preserving
existing equality semantics. That is acceptable because other adapters can use
the same metadata slot for opaque provider call annotations, and the kernel does
not inspect provider-specific keys.

#### Track E: Policy Hooks Stay Orthogonal

Goal:

`yolo`, approval, and auto-review remain execution-policy modes, not provider
features.

Implementation work:

1. Keep `yolo` as no enforceable pre-execution policy gate.
2. Keep approval as deterministic policy that can request user approval.
3. Keep auto-review as a policy hook that can call a selected review model.
4. Let auto-review default to the selected run model if no review model is
   configured.
5. Add optional config for a smaller/cheaper review model.
6. Make the review model provider-neutral:
   - it may be OpenAI;
   - it may be local OpenAI-compatible;
   - it may later be Anthropic/Gemini if those adapters support the needed
     call shape.
7. Record policy decisions as policy artifacts/events, not provider artifacts.

Exit checks:

- Changing provider does not change safety mode semantics.
- Changing safety mode does not change provider payload construction.
- Auto-review can be tested with a fake reviewer provider.

#### Track F: Token Units Everywhere

Goal:

Make budgets and visible output limits use token units, because that is the
unit the model and the user reason about.

Implementation work:

1. Search for character-based public names in budgets, reports, config, and
   model-visible text.
2. Replace public names with token names.
3. Keep internal implementation details free to use strings, but expose
   estimates as tokens.
4. Use one token estimation helper rather than scattered approximations.
5. Make truncation artifacts report original estimated tokens and visible
   estimated tokens.

Exit checks:

- No model-visible or config-facing name says `chars` when the behavior is a
  model context budget.
- Tests assert token naming in reports/artifacts.

#### Track G: Evidence And Deletion

Goal:

End with less confusion, not just more files.

Implementation work:

1. Run full tests after each major slice.
2. Run coding stress across the important provider variants.
3. Record actual metrics:
   - model calls;
   - tool calls;
   - safe batches;
   - token usage;
   - cached tokens;
   - wall time;
   - validation result;
   - final diff quality.
4. Delete old names and compatibility shims after migration.
5. Collapse duplicate request builders.
6. Delete tests that only assert legacy behavior.
7. Keep docs current, then collapse this roadmap when it stops being useful.

Exit checks:

- `rg` searches for old names are clean.
- Full test suite passes.
- `docs/MERGE.md` can be answered with concrete evidence.
- The refactor makes the provider layer easier to inspect than before.

### Phase 0: Freeze Evidence and Write Invariants

Purpose:

Before editing behavior, pin what we know and what must remain true.

Work:

1. Add this roadmap.
2. Add or update tests that assert the kernel accepts multiple `ToolCall`
   objects in one `ModelResponse`.
3. Add tests for current model-call budget behavior before renaming.
4. Add request artifact assertions for OpenAI Responses:
   - `store`;
   - tools;
   - function-call output history;
   - streaming flag;
   - usage parsing.
5. Add a tiny fixture for "model returns two read-only tool calls in one
   response."
6. Add a tiny fixture for "model returns a read and an apply_patch in one
   response" to prove mixed batches stay sequential or are split safely.

Exit criteria:

- Tests describe the intended boundary.
- The coding stress metrics are recorded in a local report or issue.
- No runtime behavior changes yet except test scaffolding if needed.

### Phase 1: Rename Budgets to Match Reality

Purpose:

Remove confusing terminology before deeper changes make it harder.

Work:

1. Rename `RunBudgets.max_turns` to `max_model_calls`.
2. Rename config keys in eval task JSON, TOML config, tests, docs, and CLI flags.
3. Rename result/report labels where they represent model calls.
4. Keep `turn_count` only for actual runtime/user turn concepts.
5. Delete compatibility aliases.

Files likely touched:

- `tinyagent/core/state.py`
- `tinyagent/core/kernel.py`
- `tinyagent/evals/runner.py`
- `tests/test_kernel.py`
- `tests/test_eval_runner.py`
- `examples/coding_stress/build-refactor-planner/task.json`
- `examples/README.md`
- any config parser or CLI docs that mention `max_turns`

Exit criteria:

- `rg "max_turns"` returns nothing except migration notes if deliberately kept.
- Reports use `model_call_count` or `max_model_calls`.
- Existing evals still run.

### Phase 2: Expand Provider Capabilities

Purpose:

Make adapter behavior explicit without adding a ProviderRouter-style framework.

Work:

1. Extend `ModelCapabilities` with only fields used by immediate code/tests:
   - `protocol`;
   - `supports_parallel_tool_calls`;
   - `supports_prompt_cache_key`;
   - `supports_stateful_responses`;
   - `supports_conversation_resource`;
   - `supports_reasoning_replay`;
   - `tool_result_mode`.
2. Update `ModelSpec.to_json_dict`.
3. Update fake, OpenAI-compatible, OpenAI Responses, and Codex provider specs.
4. Add tests for capability serialization.
5. Remove or replace the old `tool_protocol` field if it becomes redundant.

Keep this small. Do not add fields for Anthropic/Gemini until their adapters or
fixtures need them.

Exit criteria:

- Provider reports are more descriptive.
- No kernel behavior depends on provider string names.
- Capabilities are visible in run artifacts/reports.

### Phase 3: Introduce Provider Conversation State

Purpose:

Allow adapters to retain provider state handles without teaching the kernel
provider-specific semantics.

Work:

1. Add a small normalized `ModelConversationState` or equivalent.
2. Store it on `RunState` or an adapter-owned runtime slot.
3. Include it in artifacts/events as small metadata.
4. Let adapters update it from each response.
5. Ensure replay can show what state handles existed without requiring the raw
   provider payload.

OpenAI Responses state modes:

- `stateless_replay`: send full normalized history/tool history each request.
- `previous_response_id`: send only new input plus previous response id.
- `conversation`: use provider conversation resource where supported.

Initial default:

```text
stateless_replay
```

because it is simplest and privacy-conservative. But even stateless replay can
use `prompt_cache_key`.

Exit criteria:

- The state handle is recorded.
- OpenAI Responses can be configured for stateless replay with cache key.
- Tests prove state metadata does not leak huge payloads into events.

### Phase 4: Make OpenAI Responses Adapter High-Fidelity

Purpose:

Fix the known expensive behavior in the OpenAI/Codex path.

Work:

1. Add config fields:
   - `parallel_tool_calls`;
   - `prompt_cache_key`;
   - `state_mode`;
   - `include_reasoning_replay`;
   - maybe `tool_choice`.
2. Default `prompt_cache_key` to a stable thread/run/session key when supported.
3. Keep `store=false` by default.
4. Set `parallel_tool_calls=true` only when kernel/tool metadata can handle safe
   batches.
5. Parse and record usage:
   - input tokens;
   - cached input tokens;
   - output tokens;
   - reasoning tokens;
   - total tokens.
6. Parse multiple function-call output items.
7. Preserve provider response ids in adapter state.
8. Add exact request fixture tests for:
   - standard OpenAI Responses;
   - Codex subscription Responses;
   - stateless replay;
   - cache key;
   - parallel tool calls.
9. Update tests that currently assert `parallel_tool_calls: false`.

Exit criteria:

- Standard OpenAI Responses payloads are explicit and test-covered.
- Codex payload differences are explicit and test-covered.
- Coding stress rerun shows cached tokens or fewer model calls/tool batches
  where provider supports it.

### Phase 5: Add Tool Parallel-Safety Metadata

Purpose:

Let the kernel execute independent safe calls concurrently without creating a
workflow engine.

Work:

1. Add metadata to `Tool` or the tool registry:
   - `parallel_safe`;
   - `mutates_workspace`;
   - `requires_shell`;
   - `requires_network`;
   - optional `lock_key`.
2. Mark obvious tools:
   - `read_file`: parallel safe;
   - `search_code`: parallel safe;
   - `context_search`: parallel safe if source implementation is safe;
   - `context_read`: parallel safe;
   - `list_skills`: parallel safe;
   - `load_skill`: probably parallel safe;
   - `apply_patch`: not parallel safe;
   - `shell`: not parallel safe by default;
   - MCP tools: not parallel safe unless declared.
3. Add a dispatcher that groups returned tool calls:
   - all-safe batch -> concurrent execution;
   - any unsafe call -> sequential execution or split safe prefix;
   - preserve model-visible result order.
4. Record batch ids.
5. Ensure policy checks still run for each call.
6. Ensure workspace deltas and mutation events remain correct.

Exit criteria:

- Two returned `read_file` calls execute in one model cycle and produce ordered
  tool results.
- Read/read/search batches do not corrupt events.
- Patch/shell calls remain sequential.
- Tests prove unsafe mixed batches do not race.

### Phase 6: Add Model-Visible Parallel Exploration Instructions

Purpose:

Make the model actually use the capability.

Work:

1. Add profile instruction fragments gated by adapter/tool capability:
   - think through all needed reads first;
   - batch independent reads;
   - avoid sequential reads unless the next path depends on the previous result;
   - do not parallelize mutating tools;
   - after patches, verify by tests/diff instead of rereading unchanged files.
2. Keep instructions short and profile-owned.
3. Add tests or snapshots for the model-visible prompt when parallel calls are
   enabled.

Exit criteria:

- Context snapshots show the instruction only when capability is enabled.
- Coding stress run emits fewer serialized read cycles.

### Phase 7: Strengthen OpenAI-Compatible Chat Adapter

Purpose:

Keep the broad compatibility path solid and honest.

Work:

1. Add provider capability flags for common compatibility variants:
   - strict tool schema supported;
   - streaming tool call deltas supported;
   - parallel tool calls supported;
   - usage fields supported.
2. Add fixture tests from real local/provider responses.
3. Add better errors for:
   - no tool calls emitted;
   - invalid tool JSON;
   - tool call id missing;
   - server rejects `tools`;
   - server ignores streaming tool deltas.
4. Keep local model instructions concise and direct.

Exit criteria:

- Gated protocol integration tests still pass.
- Failures are user-facing provider compatibility messages, not tracebacks.

### Phase 8: Add Open Responses Compatibility Adapter

Purpose:

Support the emerging multi-provider Responses spec without assuming full OpenAI
parity.

Work:

1. Decide whether this is a new provider kind or a config mode on the Responses
   adapter.
2. Add capability declarations for stateful vs stateless.
3. Add fixtures for a non-stateful `/v1/responses` server.
4. Use Open Responses acceptance tests if practical.
5. Reject unsupported fields clearly instead of sending them and hoping.

Exit criteria:

- A provider can say "I support Responses shape but not state."
- The adapter sends only supported fields.
- Error output identifies missing capability rather than blaming the model.

### Phase 9: Native Anthropic Adapter

Purpose:

Prove the internal contract is actually provider-neutral.

Work:

1. Implement request mapping for Messages.
2. Implement response parsing for `tool_use`.
3. Implement tool result mapping with `tool_result`.
4. Add fixture tests.
5. Add usage extraction.
6. Add a gated live smoke test if credentials exist.

Exit criteria:

- A fake Anthropic response with two tool uses becomes two `ToolCall` objects.
- Tool results are serialized back in native Anthropic shape.
- Kernel code does not change.

### Phase 10: Native Gemini Adapter

Purpose:

Add a second non-OpenAI-native adapter and catch assumptions missed by
Anthropic.

Work:

1. Implement function declaration mapping.
2. Implement `functionCall` parsing.
3. Implement `functionResponse` history mapping.
4. Preserve ids/thought signatures if needed.
5. Add fixture tests.
6. Add usage extraction.

Exit criteria:

- Gemini fixtures pass through the same normalized contract.
- Kernel code does not change.

### Phase 11: Evaluation Matrix

Purpose:

Stop deciding by vibes.

Run the same suites across provider variants:

```text
fake
openai-compatible
openai-responses
openai-codex
open-responses
anthropic
gemini
```

Not all providers need live credentials in CI. Use fixture tests by default and
gated live tests locally.

Metrics:

- success;
- validation status;
- model calls;
- tool calls;
- parallel batches;
- input tokens;
- cached input tokens;
- output tokens;
- reasoning tokens;
- time to first tool;
- time to first edit;
- repeated tool calls;
- invalid tool args;
- policy denials;
- sandbox blocks;
- provider errors;
- final diff tokens;
- final diff files changed.

Exit criteria:

- The coding stress eval has a baseline report before and after the refactor.
- The OpenAI/Codex path improves either model-call count, cached tokens, or wall
  time without lowering solve quality.
- Chat-compatible and fake providers remain green.

Current report support:

`results.jsonl`, `report.md`, `comparison.json`, and `comparison.md` now expose
observed provider/protocol/adapter, provider-reported token totals, cached token
totals, reasoning tokens, and parallel batch counts. Live providers still need
actual gated runs to populate those fields with real usage.

### Phase 12: Cleanup and Deletion Pass

Purpose:

Avoid ending with two systems.

Work:

1. Delete old capability names and config aliases.
2. Delete tests that only preserve old behavior.
3. Collapse duplicate request builders.
4. Remove provider string conditionals from the kernel.
5. Update README/examples.
6. Run `rg` for old names:
   - `max_turns`;
   - `tool_protocol`;
   - hardcoded provider names in kernel;
   - `parallel_tool_calls": False` expectations.

Exit criteria:

- The new adapter layer is smaller or clearer than the old set of shims.
- `docs/MERGE.md` checklist passes honestly.

## Test Plan

### Unit Tests

Provider request builders:

- OpenAI Responses stateless request.
- OpenAI Responses request with cache key.
- OpenAI Responses request with parallel tool calls.
- OpenAI Codex request omitting unsupported fields.
- Chat Completions request with tool result messages.
- Open Responses partial-capability request.
- Anthropic Messages tool-use mapping.
- Gemini function-calling mapping.

Parsers:

- single tool call;
- multiple tool calls;
- text plus tool call if provider supports it;
- malformed tool args;
- missing tool id;
- provider usage;
- streaming tool-call argument deltas.

Kernel:

- multiple returned tool calls are recorded;
- read-only batch executes concurrently or as one batch;
- mixed safe/unsafe batch is split or made sequential;
- policy checks run per tool;
- budget checks use `max_model_calls`;
- events remain ordered and replayable.

Context/prompt:

- parallel instructions appear only when supported;
- model-visible budget names use tokens;
- tool output truncation uses token names;
- provider state metadata stays out of large event payloads.

### Integration Tests

Gated tests:

```bash
TINYAGENT_RUN_INTEGRATION=1 uv run pytest tests/integration/test_openai_compat_protocol_real.py
```

Add gated equivalents for:

- OpenAI Responses with API key;
- OpenAI Codex subscription provider;
- Open Responses local server if available;
- Anthropic if configured;
- Gemini if configured.

Current gated command shape:

```bash
TINYAGENT_RUN_INTEGRATION=1 \
TINYAGENT_INTEGRATION_PROVIDER=gemini \
TINYAGENT_MODEL_API_KEY=... \
TINYAGENT_MODEL_NAME=gemini-... \
uv run pytest tests/integration/test_native_provider_smoke_real.py
```

Use `TINYAGENT_INTEGRATION_PROVIDER=openai-responses`,
`open-responses`, `anthropic`, or `gemini` to select the native provider smoke.
For `open-responses`, set `TINYAGENT_MODEL_BASE_URL` and
`TINYAGENT_MODEL_NAME`; an API key is optional.

### Eval Runs

Use:

```bash
uv run tinyagent eval examples/coding_stress --provider openai-codex --output-dir /private/tmp/tinyagent-coding-codex-<stamp>
uv run tinyagent eval examples/coding_stress --provider openai-responses --output-dir /private/tmp/tinyagent-coding-responses-<stamp>
uv run tinyagent eval examples/coding_stress --provider openai-compatible --output-dir /private/tmp/tinyagent-coding-chat-<stamp>
```

The exact env vars depend on provider, but the report shape should be the same.

Compare:

- solve result;
- validation result;
- model-call count;
- tool-call count;
- parallel batch count;
- cached token count;
- actual provider usage;
- final diff quality.

## Acceptance Criteria

This refactor is done when:

1. The kernel has no provider-specific wire-format decisions.
2. Budget names are honest.
3. The OpenAI/Codex Responses adapter uses cache/state/parallel affordances where
   configured and supported.
4. The broad Chat Completions path still works.
5. The adapter capability model can represent partial Open Responses support.
6. At least one non-OpenAI-native adapter can be added without kernel changes,
   or fixture tests prove exactly where the remaining assumption lives.
7. Coding stress evidence improves or explains why it cannot improve.
8. Trace artifacts clearly show normalized request, provider request, provider
   response, usage, tool calls, and tool results.
9. The implementation deletes misleading old names and avoids compatibility
   clutter.
10. `docs/MERGE.md` can be answered with concrete evidence.

## Non-Goals

- Do not build a ProviderRouter.
- Do not build a plugin manager.
- Do not turn the kernel into a workflow engine.
- Do not add automatic self-modifying provider code.
- Do not support every provider in the first patch.
- Do not hide provider-specific limitations behind generic errors.
- Do not make policy decisions inside adapters.
- Do not preserve old config names if they are misleading.

## Risks

### Risk: Parallel Tools Break Trace Ordering

Mitigation:

- Preserve model-visible result order.
- Record batch ids.
- Keep mutation tools sequential.
- Add event invariant tests.

### Risk: Capability Object Becomes a Framework

Mitigation:

- Add only fields with tests and code users.
- Prefer explicit adapter configs over abstract provider negotiation.
- Delete unused fields during cleanup.

### Risk: Responses State Reduces Privacy or Replayability

Mitigation:

- Default to `store=false`.
- Make stateful provider mode explicit.
- Keep normalized request artifacts.
- Preserve stateless replay as the baseline.

### Risk: Chat-Compatible Providers Lie

Mitigation:

- Add protocol smoke tests.
- Detect invalid/missing tool-call behavior early.
- Report provider compatibility failures clearly.

### Risk: The Refactor Grows the Codebase

Mitigation:

- Track deleted old code.
- Require every new file to remove duplicated provider logic or add fixture
  coverage.
- Keep docs concise after implementation; this roadmap can be collapsed once it
  has served its purpose.

## Suggested Work Slices

Keep slices reviewable.

1. `adapter-budget-names`
   - Rename `max_turns` to `max_model_calls`.
   - Update tests/docs/examples.

2. `adapter-capabilities`
   - Expand `ModelCapabilities`.
   - Update specs and serialization.

3. `responses-cache-state-fixtures`
   - Add OpenAI Responses config knobs and request-builder tests.

4. `tool-parallel-metadata`
   - Add tool safety metadata and sequential behavior preservation.

5. `tool-parallel-dispatch`
   - Execute safe batches with ordered results.

6. `codex-responses-fidelity`
   - Align Codex request shape with cache/parallel/state learnings.

7. `chat-compat-fixtures`
   - Harden OpenAI-compatible provider behavior and errors.

8. `open-responses-partial`
   - Add partial Responses compatibility mode.

9. `native-provider-fixture`
   - Add Anthropic or Gemini fixture adapter without kernel changes.

10. `coding-stress-comparison`
    - Rerun eval matrix and write report.

## First Concrete Step

Start with the budget rename and adapter invariants.

That gives immediate clarity and reduces confusion before touching provider
behavior:

```text
max_turns -> max_model_calls
tool_protocol -> protocol/capability flags
parallel_tool_calls false-by-test -> capability-gated behavior
```

The first patch should not try to support every provider. It should make the
current code tell the truth.

After that, make OpenAI/Codex Responses excellent, because that path has the
clearest prior art and the strongest live evidence. Then use Chat Completions
and one native non-OpenAI fixture to prove the adapter boundary is real.
