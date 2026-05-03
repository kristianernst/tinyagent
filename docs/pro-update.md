I treated “core agent” as the harness layer: run loop, state, provider interface, context construction, tool dispatch, policy, execution, traces, compaction, and extension seams. I did not include TUI, desktop app, marketplace, package management, or broad tool catalogs. Web browsing is disabled in this environment, so I could inspect the GitHub repositories through the connector, but I could not verify the Cursor blog text or the current state of Cursor’s new SDK. I’m using those references conceptually, not as inspected sources.

The high-level answer: tinyagent is not far off architecturally. It already has the right microkernel instinct. What is lacking is not “more tools” or “more framework,” but a few missing intelligence-bearing primitives: dynamic context planning, typed observations, stronger execution isolation, provider capability modeling, durable transcript invariants, loop/recovery guardrails, and a real extension protocol. Those can be added without bloating the visible agent surface.

## Current tinyagent position

tinyagent already has several unusually strong choices.

It is genuinely minimal. The package has no runtime dependencies, only dev dependencies for tests/linting, and exposes a CLI entrypoint through `agentctl` rather than pulling in a large framework stack.  The README frames the first slice as a small Python kernel, CLI workflow, bounded local execution, JSONL traces, fake provider tests, and a minimal coding profile. 

The architectural split is also correct. Your design document says the core should be a small kernel plus profile plus extensions/executors/providers, while complex search, benchmark prompts, repo-map heuristics, semantic ranking, UI, and marketplace behavior should stay out of the kernel.  That is the right line.

The implementation already reflects that. The kernel wires model, profile, tools, policy, approval handling, executor, budgets, event sink, approval mode, workspace mode, sandbox mode, and hooks. Its loop builds context, calls the model, gates visible tools, dispatches tool calls, records artifacts, refreshes context, and applies finish checks.  The contracts are compact and clean: `Tool`, `ModelProvider`, `StreamingModelProvider`, `Profile`, `PolicyEngine`, `ApprovalHandler`, and `Executor` are protocols rather than a heavy inheritance hierarchy. 

The `apex-coder` profile is also more principled than many larger agents. It exposes only `shell` and `apply_patch` by default, and it has a finish gate that prevents the model from claiming verification without evidence, forces diff/file inspection after edits, asks for verification or an explanation, and requires failures or sandbox/policy limitations to be reported.  This is a good example of “less structure, more intelligence”: the model is not micromanaged, but the harness enforces important truthfulness boundaries.

The existing context system is a decent first pass. It has explicit layers for system/profile, environment, project instructions, task, context index, finish gate, checkpoint, and recent tool preview. It estimates token use, packs by priority, and selectively preserves recent failures, diffs, patches, and tests.  The context state tracks objective, constraints, files seen/changed, commands run, tests run, known facts, open issues, next steps, artifacts, and compaction count.  Compaction is deterministic and artifact-backed, which is robust and cheap. 

So the issue is not that tinyagent lacks a core. It has one. The issue is that its core is still mostly a clean agent loop, not yet a high-performance coding harness.

## What the status quo shows

Codex.rs is the strongest coding harness because it has very mature invariants around execution, context, tool routing, and session state. Its core is much larger: it includes modules for session management, compaction, context fragments, exec policy, file watching, hooks, MCP, network policy/proxy, plugins, skills, sandboxing, thread management, tools, unified exec, web search, and platform sandboxes.  The turn loop explicitly handles pre-sampling compaction, skills/plugins/apps, MCP dependencies, hooks, history preparation, sampling, token checks, mid-turn compaction, stop hooks, and pending input. 

The important thing to copy from Codex.rs is not its size. It is its invariants. For example, Codex has a `ContextManager` that owns response-item history, token information, reference context for diffing, output truncation, model-visible normalization, rollback, and call/output pairing. It enforces that every tool call has a corresponding output and every output has a corresponding call.  Its tool registry has handlers with pre/post hook payloads, mutation classification, streamed argument diffs, dispatch tracing, and telemetry.  Its router supports model-visible specs, deferred dynamic tools, MCP tools, tool search, custom/local shell calls, and parallel-support detection.  Its execution layer is far more mature: it has cancellation, timeouts, output caps, process-group handling, sandbox transforms, network sandbox policy, Windows sandbox handling, and sandbox-denial detection. 

Hermes is valuable for a different reason: it is a survivalist agent. Its main runner imports systems for memory, retries, API error classification/failover, model metadata/context probing, context compression, prompt caching, usage pricing, display, tool guardrails, trajectory saving, and provider-specific adapters.  Its compressor is especially relevant: it uses an auxiliary model, structured summary sections, “reference only” framing, resolved/pending tracking, iterative updates, tail-token protection, tool-output pruning, scaled summary budgets, and tool-call/result detail preservation.  Hermes also has a pure side-effect-free tool loop guardrail controller that detects repeated exact failures, repeated same-tool failures, and idempotent no-progress loops.  Its tool system includes plugin discovery, toolset filtering, schema sanitization, dynamic schema rewriting, argument type coercion, sync/async bridging, pre/post tool hooks, and tool-result transformation. 

Pi’s strongest idea is extension ergonomics. Extensions are TypeScript modules that can register tools, commands, shortcuts, flags, UI, persistent state, and subscribe to lifecycle events. More importantly, they can intercept context, model requests, tool calls, tool results, compaction, session lifecycle, and user input.  Pi also documents compaction as a first-class session operation: it finds a cut point, keeps recent tokens, summarizes older messages with previous summaries, saves a compaction entry, reloads the session from summary plus tail, handles split turns, tracks read/modified files, and lets extensions provide custom compaction. 

OpenCode’s main lessons are provider breadth, config-driven agents, server/session architecture, and permission sophistication. It positions itself as provider-agnostic, client/server, TUI-focused, with built-in `build`, `plan`, and `general` agents.  Its config schema supports agents, providers, MCP, LSP, skills, plugins, permission, tools, tool-output limits, and compaction settings.  Its agent config supports model, prompt, tools/permissions, mode, hidden state, steps, and per-agent options.  Its shell tool is instructive: it parses Bash/PowerShell with tree-sitter, detects path usage, asks for permissions on external directories and command patterns, supports plugin-provided shell env, streams/truncates output, saves full output, handles abort/timeouts, and returns structured metadata. 

## What is lacking in tinyagent

The core gap is dynamic context optimization.

By “context,” I mean the model-visible input: system/developer instructions, user task, environment facts, prior messages, tool results, file snippets, diffs, checkpoints, memories, and anything else sent to the model. A “context window” is the maximum amount of this input plus output the model can handle. “Compaction” is the act of replacing older context with a shorter summary. “Dynamic context optimization” is broader than compaction: it is deciding, at every turn, what the model should see, what it should not see, what should be summarized, what should be lazily retrieved, and what should be pinned because it is safety-critical or task-critical.

tinyagent currently has static layer packing plus deterministic compaction. That is good, but not enough. The current `ContextBuilder` prioritizes predefined layers and recent tool evidence.  It does not yet have a context planner that says: “for this next model call, the task stage is debugging; keep the failing test output, changed files, relevant stack traces, current diff, and last successful command; drop generic setup chatter and stale explorations.” That is the main missing Cursor-like idea.

The second gap is that tool results are not semantically rich enough. tinyagent’s `ToolResult` already has fields for output, exit code, duration, summary, preview, artifact path, truncation, failure kind, metadata, and read hints.  That is promising. But the shell tool is still mostly “run command, capture output, emit artifacts.”  A better core would extract typed observations from the two visible tools. For example, after `pytest`, the harness should know this was a test command, whether it passed, which files/tests failed, and what error class appeared. After `git diff`, it should know changed files. After `rg`, it should know query and match count. After `apply_patch`, it should know files added/deleted/modified and whether the patch was clean. This is not adding model-visible structure. It is adding harness-side understanding.

The third gap is execution isolation. tinyagent’s README explicitly says the shell is cwd-bound with sanitized env and a denylist, but not an actual sandbox.  The implementation runs commands through `subprocess.Popen(..., shell=True)` in the workspace with timeout and output management.  The policy layer is “classifier-first” and regex/shlex based; it denies common risky commands, network-looking commands, writes to evidence/secrets/run artifacts, and certain outside-workspace redirects, but it is not a real shell AST or OS sandbox.  For a best-in-class coding agent, this is a hard ceiling. The agent must be able to act boldly while the harness keeps it contained.

The fourth gap is transcript invariants. A “transcript” here means the canonical internal history of messages, model outputs, tool calls, tool results, reasoning summaries, compactions, and synthetic harness messages. Codex’s context manager normalizes history, strips unsupported images, truncates outputs, tracks token usage, rolls back turns, and enforces call/result pair integrity.  tinyagent has good run state and event logging, but it does not yet appear to have a dedicated transcript object with those invariants. Without that, context building, replay, compaction, rollback, evals, and debugging all become more ad hoc.

The fifth gap is provider capability modeling. tinyagent’s provider is currently OpenAI-compatible Chat Completions using `urllib`, with fake provider support for tests.   That is minimal, but not sufficient for “best agent.” A coding harness needs to know model context window, output limits, tool-call format, streaming behavior, parallel tool support, reasoning support, image support, prompt caching support, cost, retry behavior, and provider-specific quirks. OpenCode leans heavily into provider breadth through many AI SDK providers.  tinyagent does not need that dependency tree, but it does need a small capability object.

The sixth gap is extension protocol. tinyagent has hooks in the kernel.  But Pi shows the more powerful abstraction: user/project-local extensions can register tools, intercept context, mutate/block tool calls, modify tool results, customize compaction, add commands, and persist state.  tinyagent should not copy Pi’s whole TypeScript runtime. But it should have a tiny extension manifest and event API. Otherwise, “easy extendability” depends on modifying core Python.

The seventh gap is loop/recovery intelligence. Hermes’ guardrail controller is a good minimal pattern: it is pure, side-effect-free, and detects repeated exact failures, same-tool failure loops, and read-only no-progress loops.  tinyagent has repeated failed command checks in policy, but not a general turn-level progress model.  The core needs to know when the agent is thrashing, retrying identical commands, repeatedly reading the same data, or making edits without new evidence.

The eighth gap is eval feedback. tinyagent has replay/inspect/eval CLI surfaces.  But to become better than status quo, the traces should not just be logs. They should become training data for the harness: context waste, tool-loop causes, verification misses, policy false positives, model-call cost, patch success rate, time-to-first-edit, test-after-edit rate, and finish-gate interventions. This is how the core improves without growing much.

## What I would add, minimally

I would not add many visible tools. Keep `shell` and `apply_patch` as the default surface. That is one of tinyagent’s best choices. Instead, add these core primitives behind the surface.

First, add a `Transcript` object. It should own canonical turns, model responses, tool calls, tool outputs, compaction records, injected finish-gate messages, and rollback. It should enforce: no orphan tool outputs, no tool calls without outputs after dispatch, stable call IDs, normalized provider messages, output truncation before model visibility, and artifact pointers for large data. This borrows the Codex invariant, not the Codex size.

Second, add an `Observation` layer. A tool result is raw evidence. An observation is interpreted evidence. For example:

```python
@dataclass
class Observation:
    kind: Literal[
        "file_read", "file_changed", "diff_seen", "test_run",
        "test_failure", "command_failure", "policy_block",
        "dependency_error", "search_result", "verification"
    ]
    subject: str
    summary: str
    confidence: float = 1.0
    refs: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
```

This lets the harness understand progress without forcing the model into a rigid workflow. The model still thinks freely. The harness just knows what happened.

Third, replace static packing with a `ContextPlan`. This should be tiny:

```python
@dataclass
class ContextPlan:
    pinned: list[ContextItem]
    recent_tail_budget: int
    retrieval_queries: list[str]
    include_observation_kinds: set[str]
    omit_artifact_refs: set[str]
    reason: str
```

The profile produces the plan; the context builder executes it. The planner can be heuristic at first. Later it can be model-assisted. This is the smallest version of dynamic context optimization.

Fourth, add a `ModelCapabilities` object:

```python
@dataclass(frozen=True)
class ModelCapabilities:
    context_window: int
    max_output_tokens: int
    supports_tools: bool = True
    supports_parallel_tools: bool = False
    supports_reasoning: bool = False
    supports_images: bool = False
    supports_prompt_cache: bool = False
    tool_protocol: Literal["chat_completions", "responses", "anthropic", "gemini"]
```

This keeps the provider abstraction minimal while unlocking correct context budgeting, provider serialization, fallback, and tool-call handling.

Fifth, introduce an `ExecutionEnvelope`. This should wrap command execution with cwd, env, timeout, output caps, network policy, writable roots, process group cancellation, and sandbox backend. The default can remain local, but the interface should support stronger backends. This is where tinyagent should learn from Codex’s exec layer and OpenCode’s shell parsing.  

Sixth, add a pure `ProgressGuard`. It should inspect observations and tool calls and return guidance or a synthetic result. Keep it side-effect-free like Hermes.  This is an example of “less structure, more intelligence”: do not force a plan; just interrupt obvious loops.

Seventh, add an `ExtensionHost`, but keep it austere. The minimum viable extension protocol is:

```python
class Extension(Protocol):
    def on_context(self, event: ContextEvent) -> ContextPatch | None: ...
    def on_tool_call(self, event: ToolCallEvent) -> ToolCallPatch | Block | None: ...
    def on_tool_result(self, event: ToolResultEvent) -> ToolResultPatch | None: ...
    def on_compact(self, event: CompactEvent) -> CompactPatch | None: ...
    def tools(self) -> list[Tool]: ...
```

Then load `tinyagent.toml` or `.tinyagent/extensions/*.py`. Do not invent a plugin ecosystem yet. Just make core modification unnecessary.

Eighth, make evals harness-native. Every run should produce enough structured data to answer: Did the agent inspect before editing? Did it verify after editing? Did it retry identical failures? Did context contain the failing evidence? Did the finish gate prevent a bad final answer? Which tool outputs consumed most context? Which observations were missing?

## The most important design shift

Right now, tinyagent’s model-visible surface is minimal, but its harness intelligence is also still minimal. The goal should be:

“Minimal visible structure, maximal hidden interpretation.”

That means the model sees simple tools and concise context. The harness, however, quietly tracks typed observations, task state, verification state, file state, tool-loop state, and context relevance. The model should not be forced through a rigid planner, but the harness should continuously shape what the model sees.

The core loop would become:

```python
while not state.done:
    observations = observer.from_state(state)

    plan = profile.plan_next_context(
        state=state,
        observations=observations,
        capabilities=model.capabilities,
    )

    request = context_builder.build(state, plan)
    response = model.complete(request)

    transcript.record_model_response(response)

    for call in response.tool_calls:
        guard = progress_guard.before_call(state, call)
        if guard.blocks:
            transcript.record_synthetic_tool_result(call, guard.message)
            continue

        decision = policy.evaluate(call, state)
        result = executor.run(call, decision)

        transcript.record_tool_result(call, result)
        obs = observer.extract(call, result, workspace_diff=workspace.diff())
        state.observe(obs)

        progress_guard.after_call(state, call, result, obs)

    if context_manager.needs_compaction(state, model.capabilities):
        profile.compact(state, transcript, observations)

    finish = profile.before_finish(state, response)
    if finish.allow:
        state.finish(response.content)
```

This keeps the kernel small. The new intelligence lives in `plan_next_context`, `observer.extract`, `progress_guard`, and `Transcript`.

## Specific priority order

The first priority should be dynamic context optimization. It will compound everything else. A better context planner makes the same model look smarter, reduces wasted tokens, improves verification, and makes compaction less destructive. Start with a heuristic context planner that classifies the next turn into modes such as explore, edit, debug, verify, summarize, and finish. Then tune the selected evidence per mode.

The second priority should be typed observations. This is the highest leverage small abstraction. It lets the finish gate, context planner, evals, and loop guardrails share a common understanding of what happened. It also avoids exposing more tools to the model.

The third priority should be execution isolation. A best coding agent needs permission to act. To give it that permission, the harness must be safer. The current policy is a good start, but it should be backed by a stronger execution envelope and, eventually, a real sandbox.

The fourth priority should be provider capabilities. Without capability-aware budgeting and serialization, the core will either overfit to OpenAI-compatible Chat Completions or accumulate provider hacks. A tiny capabilities object prevents that.

The fifth priority should be the extension protocol. Pi is the reference here. But tinyagent should keep it smaller: events, tools, context patches, tool-call patches, tool-result patches, and compaction patches. No need for a full package ecosystem initially.

The sixth priority should be eval trace analysis. This is how tinyagent becomes “minimal and better” rather than “minimal and underpowered.” Every failure should point to one of a small number of harness fixes: context missing, observation missing, policy wrong, execution failed, provider malformed, loop not detected, verifier absent, finish gate weak.

## What not to copy

Do not copy Codex.rs’ surface area. It is strong, but its core is large because it supports many integrations, sandboxes, plugins, skills, MCP, network policy, thread stores, and platform-specific behavior.  tinyagent should copy its invariants.

Do not copy Hermes’ monolithic accumulation. Hermes has many practical survival mechanisms, but its main runner is still a very large orchestrator with many imported concerns.  tinyagent should copy its resilience primitives: tool-loop guardrails, JSON repair, context compression patterns, tool-result pruning, and memory fencing.

Do not copy Pi’s entire extension runtime. Copy the event model and hot-swappable extension feel. Pi’s extension docs show a broad lifecycle system with hooks from input through provider request through tool result and compaction.  tinyagent only needs the narrow subset that affects core agent quality.

Do not copy OpenCode’s dependency/provider stack. It is powerful but large. Its useful lessons are config-driven agents, permission rules, provider-agnosticism, session persistence, shell parsing, and output truncation.  

## Bottom line

tinyagent’s current core is clean, but it is still mostly an agent loop plus a good profile. To become “minimal and better,” it needs a small number of deeper invariants:

A `Transcript` that makes history safe and replayable.

An `Observation` layer that turns raw tool output into task evidence.

A `ContextPlan` that makes context dynamic instead of statically packed.

A `ModelCapabilities` layer that prevents provider hacks.

An `ExecutionEnvelope` that makes bold action safe.

A `ProgressGuard` that stops thrashing.

An `ExtensionHost` that lets users extend without modifying core.

An eval/trace analyzer that converts failures into harness improvements.

That is the path I would take. Keep the model-facing interface almost as small as it is now. Make the harness far more perceptive.
