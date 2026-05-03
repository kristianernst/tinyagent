# tinyagent Core Agent Harness Design

Status: design draft
Scope: core agent harness, not UI, marketplace, memory product, or multi-agent framework
Primary goal: make tinyagent stronger than status quo while keeping the kernel small, readable, and extensible

## 1. Executive summary

tinyagent should remain a minimal coding-agent harness whose default profile exposes only `shell` and `apply_patch`. That is the right baseline: the model can inspect, search, test, build, and use ordinary developer commands through `shell`, while edits flow through one deterministic patch primitive. The current repository already points in this direction: the README describes a small Python kernel, CLI-first workflow, bounded local execution, JSONL traces, fake provider tests, and an `apex-coder` profile; it also states that the default visible tools are only `shell` and `apply_patch`, while hidden tools are blocked if not visible in the model request. 

The main improvement should not be “add more agent structure.” The main improvement should be **better state substrate**: richer context, safer execution, better tool result semantics, replayable traces, branchable runs, and eval-driven harness iteration.

The core principle:

> Less structure in control flow. More structure in evidence, context, permissions, and traces.

This reconciles the philosophies behind tinygrad, Pi, Cursor, Codex, Hermes, OpenCode, and Manus. Pi’s public framing is especially close to tinyagent: it calls itself a minimal terminal coding harness, built around extensibility through extensions, skills, prompt templates, themes, packages, RPC, and SDK modes rather than baking in heavy features. ([Pi Dev][1]) Cursor’s recent harness work points in the same direction from another angle: they have moved away from heavy static upfront context and toward dynamic context that agents fetch while working. ([Cursor][2])

The proposed design is a small kernel plus a few high-leverage contracts:

1. `ContextFS`: artifact-backed dynamic context exposed as searchable/readable files.
2. `ContextEngine`: deterministic context packing with inclusion/exclusion traces.
3. `ToolResult` schema: structured, artifact-linked shell and patch results.
4. `PolicyEngine`: declarative allow/ask/deny permissions plus sandbox-aware failures.
5. `FinishGate`: profile-owned checks before final answer.
6. `Compactor`: deterministic extraction plus optional LLM summary, never destructive.
7. `Hook` ABI: small lifecycle extension surface.
8. `RunGraph`: branchable runs and child runs, not a graph framework.
9. `EvalLoop`: metrics and replay-based harness improvement.
10. `SDK/EventStream`: programmatic API over the same event log as the CLI.

The kernel stays small because it owns only state, eventing, model calls, tool dispatch, policy checks, artifact persistence, and replay. Profiles, hooks, and tools provide behavior.

---

## 2. Design goals

tinyagent’s design goals should be explicit because otherwise the project will drift toward a larger agent framework.

The first goal is **minimality without code golf**. The core should be small enough that one engineer can understand the whole agent loop, but it should not avoid necessary structure when structure improves correctness. The project should prefer one clear abstraction over five special cases.

The second goal is **agent quality through context, not workflow rigidity**. The model should not be forced through a planner, todo system, graph runtime, or hand-authored state machine. Instead, the harness should preserve high-quality evidence: what changed, what failed, what was omitted from context, what permissions applied, what verification ran, and what branch of the run graph the agent is in.

The third goal is **default two-tool coding**. The default `apex-coder` profile should continue to expose only `shell` and `apply_patch`. The current profile already declares exactly this tool surface.  The default system prompt also already encodes the right behavioral spine: inspect before editing, prefer repo evidence, use small patches, run focused checks, inspect git diff, avoid destructive commands, and finish with normal assistant content. 

The fourth goal is **dynamic context discovery**. Cursor’s recent work argues that agents improve when less information is injected upfront and more relevant information is made retrievable during the trajectory. Their examples include turning long tool responses into files, referencing chat history during summarization, loading only needed MCP tools, and treating terminal sessions as files. ([Cursor][2]) tinyagent already stores artifacts; the design below turns those artifacts into a model-usable context layer.

The fifth goal is **safe autonomy**. The agent should be able to work without constant confirmations inside a bounded environment, but it should not be able to accidentally modify secrets, external directories, production systems, or network resources. Cursor’s sandboxing post frames this well: command approvals alone create approval fatigue, while sandboxed agents can run freely inside constraints and ask only when they need to step outside them. ([Cursor][3])

The sixth goal is **eval-first harness development**. Cursor describes harness work as a product iteration loop using offline evals, online metrics, tool-error taxonomies, token efficiency, tool-call count, cache hit rate, and code keep rate. ([Cursor][4]) tinyagent already has JSONL traces, replay, inspect, and eval commands; the design should make those the main way to decide whether a harness change is good. 

---

## 3. Non-goals

tinyagent core should not include a workflow graph runtime. LangGraph-style orchestration may be useful for some products, but it conflicts with tinyagent’s desired design center.

tinyagent core should not include built-in todo management. If a model needs todos, it can use a file such as `TODO.md`, or an extension can add a todo tool. The kernel should not treat todos as a privileged control mechanism.

tinyagent core should not include MCP as a dependency. The core should expose a tool-provider interface. MCP can be an adapter.

tinyagent core should not include a memory product. It should expose `ContextSource` and `ContextFS`; memory can be one optional source.

tinyagent core should not include subagents as a planner framework. It should support child runs. A child run can behave like a subagent, but the kernel should not become an orchestrator.

tinyagent core should not include a plugin marketplace, package manager, or UI system. It should expose hooks. Packaging can come later.

---

## 4. Definitions

A **harness** is the code around the model: prompts, tools, context construction, execution policy, traces, compaction, and stop behavior. The model is not the agent by itself; the model plus harness is the agent.

A **kernel** is the smallest runtime that executes an agent run. It owns the loop: build context, call model, dispatch tools, record results, maybe compact, maybe finish.

A **profile** is a behavior bundle. It decides the system prompt, visible tools, context policy, model settings, compaction policy, and finish policy. `apex-coder` is currently tinyagent’s default profile. 

A **run** is one durable agent session. It has an ID, an event log, artifacts, metadata, and optionally parent/child relationships.

A **turn** is one model response cycle. A turn may contain assistant text, reasoning summaries, tool calls, and tool results.

A **tool step** is one tool invocation plus its result.

An **artifact** is durable data too large or too detailed to keep fully in model context: shell output, model payloads, diffs, search results, screenshots, summaries, or raw event payloads.

`ContextFS` is a curated, read-only, model-discoverable filesystem view over run artifacts and high-value state.

A **hook** is a callback that can observe or transform specific lifecycle objects, such as context, model request, tool call, tool result, compaction request, or finish candidate.

A **permission policy** is a declarative rule set that decides whether a requested action is allowed, denied, or requires approval.

A **finish gate** is a profile-owned check before the final answer is accepted.

---

## 5. Current tinyagent baseline

tinyagent currently has the correct first slice: a minimal Python kernel, CLI workflow, bounded local execution, JSONL traces, fake provider for deterministic tests, and a default `apex-coder` profile. 

The default tool surface is intentionally small: `shell` and `apply_patch`. The README explicitly says hidden tools such as `read_file`, `list_files`, and `search_repo` may remain registered for tests or ablations, but the kernel blocks registered tools that were not visible in the model request that produced the call. 

The current profile is small. `ApexCoderProfile` loads a system prompt, builds context through `ContextBuilder`, controls visible tool names, and delegates compaction to `compact_state`. 

The current shell design is not yet safe enough for strong autonomy. The README states that the shell runs with `cwd` set to the workspace root and a sanitized minimal environment, but also says the current milestone is policy-bounded rather than isolation-bounded and is not a sandbox. 

This design builds from those facts rather than replacing them.

---

## 6. External design lessons

Codex.rs is the robustness reference. Its core is large, but the useful lessons are not “copy all modules.” The useful lessons are context normalization, stateful sessions, policy-aware execution, tool routing, compaction, rollouts, and history management. Its library root includes modules for context, context manager, exec policy, sandboxing, tools, rollout, skills, MCP, file watching, and thread/session state.  Its context manager preserves tool-call/tool-output invariants, strips unsupported images, estimates token usage, and truncates function output payloads.  Its context updates can emit diffs for environment, permissions, collaboration mode, realtime state, personality, and model switches instead of blindly reinjecting everything.  Its tool router separates model-visible tool specs from registry dispatch and handles function calls, MCP calls, local shell calls, custom calls, and parallel support. 

Pi is the minimal extensibility reference. Pi describes itself as a minimal terminal coding harness that stays small at the core while being extended through TypeScript extensions, skills, prompt templates, themes, and packages. It also supports interactive, print/JSON, RPC, and SDK modes. ([Pi Dev][1]) Pi’s extension system can register custom tools, intercept events, block or modify tool calls, inject context, customize compaction, and add UI components. ([Pi Dev][5]) tinyagent should adopt the hook shape, not the whole TypeScript/UI system.

Cursor is the context and harness-iteration reference. Cursor’s dynamic context work says fewer details should be provided upfront as models become better at seeking context, and long tool responses, chat history, skills, MCP tools, and terminal sessions can be exposed as files for selective retrieval. ([Cursor][2]) Cursor’s harness-improvement post emphasizes offline and online measurement, token efficiency, tool-call count, cache hit rate, code keep rate, user-satisfaction signals, expected vs unknown tool errors, and model-specific harness tuning. ([Cursor][4]) Cursor also explicitly customizes tool formats and prompting per model family, noting that OpenAI and Anthropic models may perform better with different edit tool shapes because of training distribution differences. ([Cursor][6])

Cursor is also the sandboxing reference. Their sandboxing post says approvals can cause fatigue, sandboxed agents can run freely inside a controlled environment, and surfacing sandbox constraints in shell tool results helped agents recover more gracefully from sandbox-related failures. ([Cursor][3])

OpenCode is the profile/mode and permission reference. OpenCode distinguishes primary agents from subagents, ships `build` and `plan` primary agents, and uses permissions so `plan` can analyze and suggest changes without directly modifying code. ([OpenCode][7]) This maps well to tinyagent profiles, as long as the kernel does not become an agent-role framework.

Hermes is the procedural-memory reference. Its public learning-loop description says it observes repeated multi-step tasks, distills them into skills, refines those skills from feedback, uses progressive disclosure so irrelevant skills do not consume context, and can search prior sessions. ([Hermes Agent][8]) tinyagent core should not implement all of that, but it should expose enough context and hook interfaces for that kind of system to exist outside the kernel.

Cursor’s SDK is the programmatic-agent reference. Cursor’s public beta SDK exposes the same agent runtime, harness, and models used by its desktop app, CLI, and web app, and streams events from local or cloud runs. ([Cursor][9]) tinyagent should expose a smaller version: one event stream API that both CLI and SDK use.

---

## 7. Core architecture

The proposed architecture is:

```text
                 ┌────────────────────┐
                 │ CLI / SDK / Replay │
                 └─────────┬──────────┘
                           │
                    prompt / resume
                           │
                 ┌─────────▼──────────┐
                 │       Kernel       │
                 │ run loop + events  │
                 └────┬───────┬───────┘
                      │       │
              context │       │ tool calls
                      │       │
        ┌─────────────▼─┐   ┌─▼──────────────┐
        │ ContextEngine │   │   ToolRouter   │
        │ + ContextFS   │   │ + PolicyEngine │
        └──────┬────────┘   └─┬──────────────┘
               │              │
        model messages        │ allowed call
               │              │
        ┌──────▼──────┐   ┌───▼────────────┐
        │ ModelClient │   │ Executor       │
        │ providers   │   │ shell/patch    │
        └──────┬──────┘   └───┬────────────┘
               │              │
               │              ▼
               │       ┌──────────────┐
               └──────►│ ArtifactStore│
                       │ + EventLog   │
                       └──────────────┘

                 Hooks wrap each major boundary.
                 Profiles configure behavior.
```

The kernel should stay close to this pseudocode:

```python
async def run(state: RunState, profile: Profile) -> FinalAnswer:
    await hooks.on_run_start(state)

    while state.budget.remaining_steps > 0:
        if profile.should_compact(state):
            await compact(state, profile)

        built = await context_engine.build(state, profile)
        built = await hooks.on_context(state, built)

        visible_tools = profile.visible_tools(state, tool_registry)
        request = model_request_from(built, visible_tools, profile.model_options(state))
        request = await hooks.before_model_call(state, request)

        response = await model_client.complete(request)
        response = await hooks.after_model_response(state, response)
        state.record_model_response(response)

        if response.tool_calls:
            for call in tool_scheduler.order(response.tool_calls, profile):
                decision = policy_engine.evaluate(state, call)
                call = await hooks.before_tool_call(state, call, decision)

                if decision.action == "deny":
                    result = ToolResult.denied(call, decision)
                elif decision.action == "ask":
                    result = ToolResult.requires_approval(call, decision)
                else:
                    result = await tool_router.dispatch(state, call)

                result = await hooks.after_tool_result(state, result)
                state.record_tool_result(result)
            continue

        finish = await profile.before_finish(state, response)
        finish = await hooks.before_finish(state, response, finish)

        if finish.allow:
            state.done = True
            return FinalAnswer.from_response(response)

        state.inject_user_message(finish.injected_message)

    return FinalAnswer.budget_exhausted(state)
```

The kernel has no planning concept. It merely gives the profile and hooks a few decision points.

---

## 8. `ContextFS`: artifact-backed dynamic context

### 8.1 Problem

Long coding runs accumulate enormous context: shell outputs, repeated diffs, failed tests, search results, compiler errors, previous user messages, model reasoning summaries, and patches. Naively keeping these in the prompt creates token waste and contradictory stale information. Truncating them loses important evidence.

Cursor’s dynamic context pattern solves this by storing large outputs as files and letting the agent fetch only what it needs. ([Cursor][2]) tinyagent already writes artifacts, so the missing design step is to make artifacts discoverable and useful to the model.

### 8.2 Design

Every run gets a `ContextFS` directory:

```text
.tinyagent/runs/<run_id>/
  events.jsonl
  artifacts/
    ...
  context/
    INDEX.md
    task.md
    environment.md
    current_diff.md
    last_failure.md
    history/
      compacted.md
      raw.jsonl
    shell/
      0001-rg.txt
      0002-pytest.txt
      0003-git-diff.txt
    patch/
      0004-apply.patch
    model/
      last_request.json
      last_response.json
```

`ContextFS` is not the full artifact store. It is a curated view of artifacts intended for model retrieval. The model should normally see only `INDEX.md`, plus a few high-priority summaries.

Example `INDEX.md`:

```markdown
# tinyagent ContextFS

Read only what is needed. Large outputs are stored here to avoid bloating prompt context.

## Task
- task.md: original user request and current task state.

## Current repo state
- current_diff.md: latest summarized git diff.
- environment.md: cwd, OS, git branch, available commands.

## Recent failures
- last_failure.md: most recent failing command and likely next inspection target.
- shell/0007-pytest.txt: full pytest output.
  Suggested reads:
  - tail -120 .tinyagent/runs/<run_id>/context/shell/0007-pytest.txt
  - rg "FAILED|ERROR|Traceback|AssertionError" .tinyagent/runs/<run_id>/context/shell/0007-pytest.txt

## History
- history/compacted.md: continuation summary.
- history/raw.jsonl: exact prior events if needed.
```

The model reads these files through `shell`. No new default tool is required.

### 8.3 Tool result rendering

Every large tool result should return a short preview and an artifact reference:

```json
{
  "tool": "shell",
  "call_id": "tool_17",
  "exit_code": 1,
  "duration_ms": 1842,
  "cwd": "/workspace/project",
  "preview": "FAILED tests/test_context.py::test_contextfs_index ... AssertionError",
  "truncated": true,
  "artifact": ".tinyagent/runs/2026-05-03T.../context/shell/0017-pytest.txt",
  "read_hints": [
    "tail -120 .tinyagent/runs/.../context/shell/0017-pytest.txt",
    "rg \"FAILED|ERROR|Traceback\" .tinyagent/runs/.../context/shell/0017-pytest.txt"
  ]
}
```

The preview should be useful but bounded. The artifact should contain the exact output.

### 8.4 Read-only guarantee

`ContextFS` should be readable by the agent but not editable by `apply_patch` or shell commands. The current tinyagent shell is not an actual sandbox, so policy alone is insufficient for a hard guarantee.  The initial implementation should enforce this at the tool layer:

`apply_patch` rejects paths under `.tinyagent/**`.

`shell` policy rejects obvious writes to `.tinyagent/**`.

A future sandboxed executor enforces filesystem write denial for `.tinyagent/**`.

This matters because `ContextFS` is evidence. The agent must not be able to rewrite evidence.

---

## 9. `ContextEngine`: deterministic context packing

### 9.1 Problem

The current profile delegates context construction to `ContextBuilder`, but the design should become more explicit: what was included, what was excluded, why, and at what token cost. 

### 9.2 Data model

```python
@dataclass(frozen=True)
class ContextItem:
    id: str
    role: Literal["system", "developer", "user", "assistant", "tool"]
    text: str
    source: str
    priority: int
    token_estimate: int
    stable: bool = False
    tags: tuple[str, ...] = ()
    expires_after_steps: int | None = None

@dataclass(frozen=True)
class ContextExclusion:
    item_id: str
    reason: Literal[
        "budget",
        "expired",
        "lower_priority",
        "duplicate",
        "profile_filtered",
    ]
    token_estimate: int

@dataclass(frozen=True)
class BuiltContext:
    messages: list[Message]
    included: list[ContextItem]
    excluded: list[ContextExclusion]
    token_estimate: int
    contextfs_index_path: str | None
```

### 9.3 Context sources

The context engine should collect candidates from:

`system_prompt`: profile system prompt.

`task`: current user request and injected continuation messages.

`project_instructions`: `AGENTS.md`, profile docs, or equivalent.

`environment`: cwd, OS, git branch, command preflight, shell availability.

`repo_state`: git status, current diff summary, changed files.

`recent_tool_previews`: last N bounded tool results.

`failures`: current failure summary and next inspection hints.

`history_summary`: compacted continuation summary.

`contextfs_index`: `ContextFS/INDEX.md`.

`hooks`: optional external context sources.

### 9.4 Packing policy

The default packing algorithm:

1. Include stable critical items: system prompt, current user request, safety/policy context.
2. Include current task state and `ContextFS/INDEX.md`.
3. Include active failure and current diff summary if present.
4. Include recent tool previews until budget.
5. Include compacted summary if prior history was compressed.
6. Preserve the most recent user/model/tool tail.
7. Exclude lower-priority items with explicit `ContextExclusion` records.

This should be deterministic for replay. A run inspected later should explain why context was present or absent.

### 9.5 Context budget report

Every model call should write a context report artifact:

```json
{
  "request_id": "model_22",
  "token_estimate": 18742,
  "budget": 64000,
  "included": [
    {"id": "system:apex-coder", "tokens": 420, "priority": 1000},
    {"id": "contextfs:index", "tokens": 950, "priority": 900},
    {"id": "failure:last", "tokens": 600, "priority": 850}
  ],
  "excluded": [
    {"id": "shell:0004", "tokens": 9000, "reason": "budget"}
  ]
}
```

This turns context engineering into something debuggable.

---

## 10. Tool design

### 10.1 Default tools

The default `apex-coder` profile should continue to expose:

```text
shell
apply_patch
```

This is already the current default. 

`read_file`, `list_files`, and `search_repo` may remain hidden for tests and ablations, but not visible by default. This is also already the current posture. 

### 10.2 Tool call schema

```python
@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]
    raw_args: str | None
    model_request_id: str
    visible_in_request: bool
```

If `visible_in_request` is false, the kernel rejects the call before policy evaluation.

### 10.3 Tool result schema

```python
@dataclass(frozen=True)
class ToolResult:
    call_id: str
    tool: str
    ok: bool
    exit_code: int | None
    duration_ms: int
    summary: str
    content_preview: str
    artifact_path: str | None
    truncated: bool
    failure_kind: FailureKind | None
    metadata: dict[str, Any]
    read_hints: list[str]
```

Failure kinds:

```python
class FailureKind(str, Enum):
    INVALID_TOOL_ARGS = "invalid_tool_args"
    COMMAND_FAILED = "command_failed"
    TIMEOUT = "timeout"
    SANDBOX_BLOCKED = "sandbox_blocked"
    POLICY_DENIED = "policy_denied"
    CONTEXT_OVERFLOW = "context_overflow"
    MODEL_EMPTY_RESPONSE = "model_empty_response"
    UNKNOWN = "unknown"
```

Cursor’s harness post treats unknown tool errors as harness bugs and classifies expected errors by cause, which is the model to follow here. ([Cursor][4])

### 10.4 Shell result formatting

Codex’s core formats shell output with exit code, duration, truncation, and structured/freeform variants.  tinyagent should adopt that level of metadata without adopting Codex’s full machinery.

Shell results should include:

```text
exit_code
duration_ms
cwd
stdout_head
stdout_tail
stderr_head
stderr_tail
total_lines
truncated
artifact_path
command_normalized
failure_kind
sandbox_constraint
```

The model-visible result can stay small.

### 10.5 Tool scheduling

Default: sequential.

Optional future mode: parallel read-only tool calls, but only if the profile opts in and the tools declare `side_effect_free=True`.

Do not parallelize edits by default.

---

## 11. Policy and sandboxing

### 11.1 Problem

The current shell is not a sandbox.  A strong autonomous coding agent needs an execution boundary, not just a prompt telling it not to do destructive things.

Cursor’s sandboxing article gives the rationale: approvals alone create fatigue, and a constrained execution environment lets agents act freely within safe boundaries. ([Cursor][3])

### 11.2 Permission model

Use a declarative policy:

```toml
[permission]
read = "allow"
edit = "allow"
network = "deny"
external_directory = "ask"
contextfs_write = "deny"

[permission.bash]
"git status*" = "allow"
"git diff*" = "allow"
"rg *" = "allow"
"sed *" = "allow"
"pytest *" = "allow"
"uv run pytest*" = "allow"
"npm test*" = "allow"
"rm *" = "deny"
"git push*" = "deny"
"curl *" = "ask"
```

`ask` behavior depends on runtime:

Interactive CLI: ask user.

Non-interactive/eval: return `POLICY_DENIED` unless an explicit approval strategy is configured.

SDK: emit approval event and let caller respond.

### 11.3 Policy decision schema

```python
@dataclass(frozen=True)
class PolicyDecision:
    action: Literal["allow", "ask", "deny"]
    reason: str
    matched_rule: str | None
    permission: str
    suggested_approval: dict[str, Any] | None = None
```

### 11.4 Sandbox modes

```text
executor.mode = local | worktree | container | os_sandbox
network = allow | ask | deny
external_paths = allow | ask | deny
secrets = deny
```

Initial implementation can be policy-only. The target implementation should include at least `worktree` and `container` modes, and OS-native sandbox adapters if practical.

### 11.5 Sandbox-aware failures

When a command fails because of policy or sandbox constraints, the shell result should say so explicitly:

```json
{
  "ok": false,
  "failure_kind": "sandbox_blocked",
  "sandbox_constraint": "network denied",
  "summary": "Command tried to access the network, but network is denied for this run.",
  "hint": "Use local documentation/cache, or request network permission if necessary."
}
```

Cursor’s sandboxing writeup says surfacing the responsible sandbox constraint in shell results helped agents recover more gracefully. ([Cursor][3])

---

## 12. Finish gate

### 12.1 Problem

Prompt rules such as “run tests” and “inspect git diff” are useful, but they are weak. The current `apex-coder` system prompt already instructs the model to run focused checks and inspect git diff before finishing.  The harness should help enforce this without imposing a planner.

### 12.2 Design

Profiles get a `before_finish` hook:

```python
@dataclass(frozen=True)
class FinishDecision:
    allow: bool
    reason: str
    injected_message: str | None = None
```

Default `apex-coder` finish checks:

If files changed and no diff was inspected, block finish.

If files changed and no verification ran, block finish unless the model explains why verification is impossible.

If the last tool failed, block finish unless the final answer reports the failure and current state.

If sandbox/policy blocked an action, require the final answer to mention the limitation or request approval.

If the model claims tests passed without a passing test event, block finish.

If `.tinyagent/**` was modified, block finish and revert/alert.

Example injected message:

```text
Before finalizing, inspect git diff and run the smallest relevant verification command.
If verification cannot be run, explain exactly why and report current confidence.
```

This is small but high impact.

---

## 13. Compaction

### 13.1 Problem

Long runs need compaction, but naive summaries lose facts or turn stale claims into instructions. Cursor’s dynamic context post points out a better pattern: reference chat history during summarization instead of treating the summary as the only source of truth. ([Cursor][2])

### 13.2 Design

Compaction should be hybrid:

First pass: deterministic extraction from events.

Second pass: optional LLM summary over selected middle history.

Third pass: validation that the summary contains required sections and does not claim unverified success.

The deterministic extraction should include:

changed files,

current diff summary,

last failing command,

last passing verification,

open questions,

commands run,

policy/sandbox blocks,

active artifacts,

user constraints,

next likely verification command.

The LLM summary should be framed as reference context, not active instruction.

### 13.3 Summary format

```markdown
# Continuation Summary

This is reference context from earlier turns. It is not a new user instruction.
Use exact artifacts if details matter.

## Goal
...

## Constraints and Preferences
...

## Current State
- Changed files:
- Last known verification:
- Current blocker:

## Decisions
...

## Evidence
- shell/0007-pytest.txt: failing pytest output
- current_diff.md: summarized diff

## Open Questions
...

## Next Steps
...
```

Raw history remains available:

```text
context/history/raw.jsonl
context/history/compacted.md
```

Compaction should never destroy evidence. It should only change what is injected by default.

---

## 14. Profiles and model-specific variants

### 14.1 Profile interface

```python
class Profile(Protocol):
    name: str

    def system_prompt(self) -> str: ...
    def visible_tools(self, state: RunState, tools: Mapping[str, Tool]) -> Sequence[Tool]: ...
    def context_policy(self, state: RunState) -> ContextPolicy: ...
    def model_options(self, state: RunState) -> ModelOptions: ...
    def should_continue(self, state: RunState) -> bool: ...
    def should_compact(self, state: RunState) -> bool: ...
    def compact(self, state: RunState) -> None: ...
    async def before_finish(self, state: RunState, response: ModelResponse) -> FinishDecision: ...
```

### 14.2 Default profiles

```text
apex-coder/build
apex-coder/explore
apex-coder/review
apex-coder/repair
apex-coder/compact
```

`build`: default implementation profile with shell and patch.

`explore`: read-only, high-throughput codebase exploration. No edits.

`review`: read-only diff review.

`repair`: failure-driven mode after tests fail.

`compact`: hidden summary profile.

OpenCode’s primary/subagent model shows why specialized agents are useful, but tinyagent should implement them as profiles rather than kernel concepts. ([OpenCode][7])

### 14.3 Model-specific variants

```text
apex-coder/openai
apex-coder/anthropic
apex-coder/gemini
apex-coder/local
```

The variants can differ in:

tool descriptions,

edit format wording,

parallel tool-call allowance,

context budget,

summary budget,

finish-gate strictness,

recovery prompts,

model-specific tool argument repair.

Cursor’s harness post explicitly says they customize harnesses per model and provider, including tool formats and prompts. ([Cursor][6]) tinyagent should put this in profiles, not kernel branches.

---

## 15. Hooks and extensions

### 15.1 Design

The hook system should be small and typed:

```python
class TinyHook(Protocol):
    async def on_run_start(self, state: RunState) -> None: ...
    async def on_context(self, state: RunState, context: BuiltContext) -> BuiltContext: ...
    async def before_model_call(self, state: RunState, request: ModelRequest) -> ModelRequest: ...
    async def after_model_response(self, state: RunState, response: ModelResponse) -> ModelResponse: ...
    async def before_tool_call(
        self,
        state: RunState,
        call: ToolCall,
        decision: PolicyDecision,
    ) -> ToolCall | ToolBlock: ...
    async def after_tool_result(self, state: RunState, result: ToolResult) -> ToolResult: ...
    async def before_compact(self, state: RunState, request: CompactRequest) -> CompactRequest: ...
    async def before_finish(
        self,
        state: RunState,
        response: ModelResponse,
        decision: FinishDecision,
    ) -> FinishDecision: ...
```

Hooks are loaded from config:

```toml
[hooks]
paths = [
  ".tinyagent/hooks/protect_env.py",
  ".tinyagent/hooks/checkpoint_git.py"
]
```

### 15.2 Hook principles

Hooks can mutate structured objects, not raw prompt strings alone.

Every hook invocation is recorded as an event.

Hook errors are isolated and classified.

Hooks cannot bypass policy unless explicitly configured.

Hooks should not be required for the default agent.

Pi’s extension system shows the power of event interception, custom tools, context injection, and custom compaction, but tinyagent should start with a minimal Python hook ABI rather than a broad UI/plugin runtime. ([Pi Dev][5])

---

## 16. Run graph: branching and child runs

### 16.1 Problem

Replay is useful, but strong agent work often needs retry, fork, and isolated exploration. Pi emphasizes session trees and branching; Cursor and OpenCode both point toward specialized agents/subagents; Hermes uses long-running memory and skills. ([Pi Dev][10])

tinyagent should support this without adopting a graph framework.

### 16.2 Data model

```python
@dataclass(frozen=True)
class RunMeta:
    run_id: str
    parent_run_id: str | None
    parent_event_id: str | None
    profile: str
    workspace: str
    created_at: str
    branch_name: str | None
```

A run can be forked:

```bash
agentctl fork .tinyagent/runs/<run_id> --at <event_id>
```

A run can spawn a child run:

```python
child = await runner.spawn_child(
    parent=state,
    profile="apex-coder/explore",
    prompt="Find all call sites of parse_config and summarize likely breakages.",
)
```

The parent receives only the child’s summary artifact, not the full child transcript by default.

### 16.3 Child-run semantics

Child runs are isolated.

Child runs have their own policy.

Child runs write their own artifacts.

Child summaries are referenced in parent `ContextFS`.

No child run can edit parent state unless the parent explicitly applies its output.

This supports subagent-like behavior while keeping the kernel simple.

---

## 17. SDK and event stream

### 17.1 Principle

The CLI should be a client of the SDK, not a separate control path.

Cursor’s SDK exposes an event-streaming agent runtime for local and cloud runs. ([Cursor][9]) Pi also exposes RPC and SDK modes. ([Pi Dev][1]) tinyagent should expose the same small idea:

```python
async for event in tinyagent.run(
    prompt="Fix the failing parser tests",
    workspace=".",
    profile="apex-coder/build",
):
    print(event)
```

### 17.2 Public API

```python
class Agent:
    @classmethod
    def create(
        cls,
        *,
        workspace: str,
        profile: str = "apex-coder/build",
        provider: ProviderConfig,
        hooks: list[TinyHook] = (),
        policy: PolicyConfig | None = None,
    ) -> "Agent": ...

    async def run(self, prompt: str) -> AsyncIterator[Event]: ...
    async def resume(self, run_id: str) -> AsyncIterator[Event]: ...
    async def fork(self, run_id: str, event_id: str) -> "Agent": ...
```

### 17.3 Event types

```text
run.started
context.built
model.requested
model.response.started
model.response.completed
tool.call.started
tool.call.completed
policy.denied
sandbox.blocked
artifact.written
compaction.started
compaction.completed
finish.blocked
run.completed
run.failed
```

JSONL traces and SDK events should be the same objects.

---

## 18. Eval and telemetry loop

### 18.1 Why this matters

Cursor’s harness-improvement process makes a key point: harness changes need instrumentation, offline evals, online metrics, and error taxonomy, because otherwise “better” is too subjective. ([Cursor][4]) tinyagent has the right foundation: eval, replay, inspect, fake provider, and JSONL traces. 

### 18.2 Run metrics

Every run should record:

```text
tokens_in
tokens_out
context_token_estimate
context_items_included
context_items_excluded
tool_call_count
tool_error_count
tool_error_kinds
repeated_tool_call_count
files_changed
patch_count
diff_inspected_before_finish
verification_ran_after_edit
last_tool_failed_before_finish
finish_gate_blocks
compaction_count
artifact_bytes_written
sandbox_blocks
policy_denials
wall_time_ms
```

### 18.3 Eval dimensions

Quality:

task solved,

tests pass,

diff minimality,

no unrelated edits,

user constraints preserved,

no fabricated verification.

Efficiency:

tool calls,

tokens,

wall time,

context size,

irrelevant command count.

Robustness:

recovers from failing test,

recovers from bad search,

does not loop on repeated command,

survives context compaction,

does not edit protected files.

Safety:

network denied by default,

external directory denied/asked,

`.env` protected,

destructive commands denied,

ContextFS not modified.

### 18.4 Harness change acceptance

A harness change should be accepted when it improves at least one target metric without regressing critical safety or correctness metrics.

Example acceptance rule:

```text
Accept if:
- solve rate improves by >= 3% on tiny eval suite, or
- median tool calls decrease by >= 10% with no solve-rate drop, or
- premature finishes decrease by >= 20%,

and:
- protected-file violations remain zero,
- unknown tool errors do not increase,
- token usage does not increase by > 15% unless solve rate improves.
```

### 18.5 Error taxonomy

Unknown errors should be treated as harness bugs. Expected errors should be classified. Cursor’s harness article explicitly uses this framing for tool failures. ([Cursor][4])

```python
class ErrorKind(str, Enum):
    UNKNOWN = "unknown"
    MODEL_INVALID_ARGS = "model_invalid_args"
    TOOL_TIMEOUT = "tool_timeout"
    TOOL_COMMAND_FAILED = "tool_command_failed"
    POLICY_DENIED = "policy_denied"
    SANDBOX_BLOCKED = "sandbox_blocked"
    PROVIDER_ERROR = "provider_error"
    CONTEXT_OVERFLOW = "context_overflow"
    USER_ABORTED = "user_aborted"
```

---

## 19. Proposed repository structure

```text
agentd/
  kernel.py              # main loop
  state.py               # RunState, event state
  events.py              # typed event schema
  artifacts.py           # artifact store
  context_engine.py      # ContextItem, packing
  contextfs.py           # ContextFS writer/indexer
  profiles.py            # Profile interface + apex-coder
  model.py               # provider abstraction
  tools/
    __init__.py
    shell.py
    apply_patch.py
    router.py
    results.py
  policy.py              # allow/ask/deny rules
  executor.py            # local/worktree/container execution
  compaction.py          # deterministic + optional model summary
  hooks.py               # hook ABI
  evals.py               # eval runner support
  sdk.py                 # public async API

profiles/
  apex-coder/
    system.md
    build.toml
    explore.toml
    review.toml
    repair.toml

docs/
  DESIGN.md
  CONTEXTFS.md
  POLICY.md
  HOOKS.md
```

The file tree is intentionally boring. The design should not require a new framework vocabulary.

---

## 20. Detailed data schemas

### 20.1 Event

```python
@dataclass(frozen=True)
class Event:
    id: str
    run_id: str
    parent_id: str | None
    timestamp: str
    type: str
    actor: Literal["user", "assistant", "tool", "kernel", "hook", "policy"]
    payload: dict[str, Any] | None
    artifact_ref: str | None
    summary: str | None
```

### 20.2 RunState

```python
@dataclass
class RunState:
    run_id: str
    workspace: Path
    profile_name: str
    messages: list[Message]
    tool_steps: list[ToolStep]
    events: list[Event]
    artifacts: ArtifactStore
    context_checkpoint_event_id: str | None
    context_token_estimate: int
    done: bool = False
```

### 20.3 Artifact manifest

```python
@dataclass(frozen=True)
class Artifact:
    id: str
    path: str
    kind: Literal[
        "shell_output",
        "patch",
        "model_request",
        "model_response",
        "context_report",
        "summary",
        "diff",
        "raw_event_payload",
    ]
    created_at: str
    bytes: int
    sha256: str
    event_id: str | None
    model_visible: bool
```

### 20.4 Policy

```python
@dataclass(frozen=True)
class PolicyRule:
    permission: str
    pattern: str
    action: Literal["allow", "ask", "deny"]

@dataclass(frozen=True)
class PolicyConfig:
    default: Literal["allow", "ask", "deny"]
    rules: list[PolicyRule]
```

### 20.5 Hook result

```python
@dataclass(frozen=True)
class HookResult:
    changed: bool
    reason: str | None
    event_payload: dict[str, Any]
```

---

## 21. Implementation phases

### Phase 1: Tool results and `ContextFS`

Implement structured `ToolResult`.

Write full shell output to artifacts.

Generate `context/INDEX.md`.

Return artifact paths and read hints in tool results.

Deny `apply_patch` edits under `.tinyagent/**`.

Add context report artifacts for each model call.

Acceptance criteria:

Long test output does not bloat prompt context.

The model can inspect full output via `shell`.

Replay shows exact tool output artifact.

### Phase 2: `ContextEngine v2`

Introduce `ContextItem`, `BuiltContext`, and `ContextExclusion`.

Record included/excluded context.

Inject `ContextFS/INDEX.md`.

Add priority-based packing.

Acceptance criteria:

Every model request has an inspectable context report.

Budget exclusions are explainable.

Compaction and recent tool previews are not mixed ad hoc.

### Phase 3: Finish gate

Implement profile-owned `before_finish`.

Block finish after edits unless diff was inspected.

Block finish after edits unless verification ran or impossibility was explained.

Block finish after failed final tool unless failure is reported.

Acceptance criteria:

Eval tasks show fewer premature “done” answers.

The model inspects git diff before finalizing after edits.

### Phase 4: Policy engine

Implement declarative allow/ask/deny rules.

Classify failures as `POLICY_DENIED`.

Add repeated identical command guard.

Protect `.env`, `.tinyagent`, external directories, and network by default.

Acceptance criteria:

Dangerous commands are denied.

Read-only profiles cannot edit.

External directory access is visible and controlled.

### Phase 5: Sandboxed executor

Add `worktree` execution mode.

Add `container` mode if practical.

Make sandbox constraints explicit in tool results.

Acceptance criteria:

Agent can run tests and builds in sandbox/worktree mode.

Blocked network/external access is explained to the model.

### Phase 6: Hooks and SDK

Add typed hook ABI.

Record hook invocations.

Expose async event-stream SDK.

Make CLI use SDK internally.

Acceptance criteria:

A hook can block `.env` reads.

A hook can inject extra context.

SDK run and CLI run produce the same event schema.

### Phase 7: Run graph

Add `parent_run_id` and `parent_event_id`.

Implement `agentctl fork`.

Implement child runs for `explore` and `review`.

Acceptance criteria:

A run can be forked from a prior event.

A child run summary appears in parent `ContextFS`.

### Phase 8: Eval harness

Add metric extraction.

Add failure taxonomy.

Add eval report.

Add regression thresholds.

Acceptance criteria:

Harness changes can be compared by solve rate, tokens, tool calls, finish-gate blocks, and error kinds.

---

## 22. Example end-to-end flow

User:

```text
Fix the failing parser tests.
```

Kernel creates run:

```text
.tinyagent/runs/2026-05-03T.../
```

Context engine builds initial context:

```text
system prompt
task
environment
git status
ContextFS index
```

Model calls:

```text
shell {"cmd": "pytest tests/test_parser.py -q"}
```

Shell result:

```text
Preview says one parser test failed.
Full output written to context/shell/0001-pytest.txt.
```

Model calls:

```text
shell {"cmd": "tail -120 .tinyagent/runs/.../context/shell/0001-pytest.txt"}
```

Model inspects code:

```text
shell {"cmd": "sed -n '1,220p' src/parser.py"}
```

Model edits:

```text
apply_patch {...}
```

Finish gate later blocks premature finish:

```text
Before finalizing, inspect git diff and run the smallest relevant verification command.
```

Model runs:

```text
shell {"cmd": "git diff -- src/parser.py && pytest tests/test_parser.py -q"}
```

Finish gate allows final answer only after the verification event exists.

Final answer summarizes:

```text
Changed parser handling for escaped separators.
Verified with pytest tests/test_parser.py -q.
```

The run contains:

```text
events.jsonl
context/INDEX.md
context/current_diff.md
context/shell/0001-pytest.txt
context/shell/0005-verification.txt
artifacts/model/...
artifacts/context_report/...
```

---

## 23. Risks and mitigations

Risk: `ContextFS` becomes another prompt dump.
Mitigation: inject only the index and a few summaries. Store everything else as files.

Risk: the agent modifies its own evidence.
Mitigation: deny `.tinyagent/**` edits in `apply_patch`, shell policy, and sandbox.

Risk: compaction hallucinates.
Mitigation: deterministic extraction first, raw history preserved, summary framed as reference, required sections validated.

Risk: policy blocks ordinary development commands.
Mitigation: start with permissive workspace-local reads/build/test commands and strict external/network/secrets rules.

Risk: hooks make behavior non-replayable.
Mitigation: record hook inputs/outputs and hook versions in events.

Risk: profile variants bloat the project.
Mitigation: variants are small config/prompt differences, not separate kernels.

Risk: child runs become a multi-agent framework.
Mitigation: child runs are just runs with parent IDs and summary artifacts.

Risk: evals optimize for toy tasks.
Mitigation: combine deterministic unit evals with real replay inspection and metrics.

---

## 24. Design invariants

The kernel never executes a tool that was not visible in the model request.

The kernel never injects a large artifact directly when a file reference would work.

Every model request has a context report.

Every large tool output has an artifact.

Every tool failure has a failure kind.

Every final answer after edits must be supported by either verification or an explicit inability to verify.

Every policy denial is visible to both trace and model.

Every compaction preserves raw history.

Every hook invocation is recorded.

Every profile can be tested with a fake provider.

---

## 25. Why this is minimal and better

This design does not add a planner. It does not add a graph runtime. It does not add many default tools. It does not add built-in memory, MCP, todo systems, or marketplaces.

It makes the small loop better by improving the objects that pass through it:

context becomes traceable,

artifacts become retrievable,

tool results become semantically useful,

policy becomes explicit,

finish becomes verifiable,

compaction becomes evidence-preserving,

extensions become typed hooks,

sessions become branchable,

harness changes become measurable.

That is the core thesis for tinyagent:

> The agent loop should stay tiny. The state around the loop should become excellent.

[1]: https://pi.dev/?utm_source=chatgpt.com "Pi Coding Agent"
[2]: https://cursor.com/blog/dynamic-context-discovery?utm_source=chatgpt.com "Dynamic context discovery · Cursor"
[3]: https://cursor.com/blog/agent-sandboxing?utm_source=chatgpt.com "Implementing a secure sandbox for local agents · Cursor"
[4]: https://cursor.com/blog/continually-improving-agent-harness?utm_source=chatgpt.com "Continually improving our agent harness · Cursor"
[5]: https://pi.dev/docs/latest/extensions?utm_source=chatgpt.com "Pi Coding Agent"
[6]: https://cursor.com/blog/continually-improving-our-agent-harness?utm_source=chatgpt.com "Continually improving our agent harness · Cursor"
[7]: https://opencode.ai/docs/agents/?utm_source=chatgpt.com "Agents | OpenCode"
[8]: https://hermes-agent.ai/features/learning-loop?utm_source=chatgpt.com "Learning Loop — Hermes Gets Better"
[9]: https://cursor.com/blog/typescript-sdk?utm_source=chatgpt.com "Build programmatic agents with the Cursor SDK · Cursor"
[10]: https://pi.dev/docs/latest?utm_source=chatgpt.com "pi.dev"
