Created a Markdown copy here: [agent_harness_design_spec.md](sandbox:/mnt/data/agent_harness_design_spec.md)

Below is the engineering-facing spec.

# Design Specification: Minimal General-Purpose Agent Harness

Status: directional engineering specification
Audience: core engineering, platform, product engineering, evals, security
Date: April 23, 2026

## 1. Executive direction

We are building a general-purpose agent harness with a deliberately small core and an aggressively optimized default profile.

The core should remain small enough that a modern frontier model can read it, understand it, and propose meaningful changes to it inside one context window. The optimized profile should be where most capability work happens: context construction, search policy, tool orchestration, compression, verification, subagent strategy, self-extension, and benchmark-specific tuning.

This is not intended to become a conventional agent framework with many layers of abstraction. The intended shape is closer to a tiny **agent virtual machine** plus a first-class **operating profile**.

The design target is:

```text
small core
strong defaults
YOLO execution inside a bounded workspace
full traceability
model-provider neutrality
support for delegated external coding agents
language-extensible plugin system
benchmarkable harness evolution
```

The primary implementation should begin in **Python** because the founder/team has higher Python fluency and because harness iteration speed matters more than raw runtime performance at this stage. **TypeScript** should be a first-class SDK and extension layer because it fits web applications, npm distribution, and copyable extension patterns. **Rust** should be reserved for a later hardened executor/sandbox layer once the kernel/profile boundary is stable.

The thesis is not “Python beats TypeScript” or “Python beats Rust.” The thesis is that the first-order bottleneck is not runtime speed. It is harness design.

## 2. Core thesis

The strongest agent systems are not only stronger because of the model. They are stronger because of the **harness**.

A harness is the software around the model: context construction, tool definitions, shell execution, file access, workspace isolation, retries, tracing, compression, verification, memory, extension loading, and policy. The harness determines what the model sees, what actions it can take, how tool results are returned, when history is compacted, and how the system decides it is done.

The system should therefore optimize the harness as a first-class artifact. We should treat the harness profile like a model architecture: it needs ablations, metrics, regression tests, traces, and continuous improvement.

The major design decision is to separate:

```text
Kernel       minimal event loop and runtime contract
Profile      opinionated, highly optimized behavior layer
Extensions   optional tools, hooks, commands, workflows, skills
Executors    local/remote/sandboxed execution backends
Providers    raw model providers and delegated agent providers
```

This separation lets the core remain elegant while the default profile becomes extremely capable.

## 3. Definitions

**Kernel**
The smallest runtime that owns state, calls the model, executes tools, records events, and invokes profile hooks.

**Profile**
A bundle of policies and prompt/context/tool behavior that determines how the agent acts. The flagship profile should be deeply opinionated and tuned.

**Context window**
The maximum amount of tokenized information the model can consider for one inference call. It includes system/developer/user messages, tool schemas, tool results, file snippets, summaries, and generated output.

**Tool call**
A structured request emitted by the model to invoke an external function, such as `shell`, `read_file`, `apply_patch`, `search_repo`, or `spawn_agent`.

**Executor**
The process that actually performs side effects, such as running a shell command, editing files, reading a repo, or launching a container.

**Workspace**
The bounded area in which the agent is allowed to operate. The default workspace should be a git worktree or container.

**Event log**
The exact chronological record of model calls, tool calls, tool results, diffs, policy decisions, and final outputs.

**Compressor**
The component that converts long event history into compact structured state.

**Retriever**
The component that can pull exact prior artifacts, file regions, command outputs, or trace fragments back into context.

**Model provider**
A raw model backend, such as OpenAI API, Anthropic API, Gemini API, OpenRouter, local OpenAI-compatible endpoints, Ollama, vLLM, or similar.

**Agent provider**
An external agent/harness backend, such as Codex CLI, Claude Code, Gemini CLI, OpenCode, or another coding agent that can be delegated a task.

**YOLO mode**
Non-interruptive execution inside a defined trust boundary. YOLO means the agent acts without asking for approval on normal workspace operations. It does not mean unrestricted host access.

## 4. Product and engineering goals

The goal is to build the most powerful general-purpose harness through simplicity, modularity, traceability, and relentless profile optimization.

The system should be able to:

```text
operate as a local coding agent
operate as an always-on background agent
delegate work to external agent CLIs
use raw model APIs directly
support multiple model providers
support official subscription-backed coding-agent clients where available
run in YOLO mode by default inside a bounded workspace
support self-extension without losing runtime control
support TypeScript and Python extensions
produce replayable traces
run repeatable evals
optimize itself through benchmark and trace review
support /autoresearch-style metric optimization workflows
remain small and readable at the core
```

## 5. Non-goals

The first version should not try to be:

```text
a full LangGraph-style workflow engine
an IDE replacement
a web-only app
a Rust-first terminal clone
a one-provider OpenAI wrapper
a pure MCP host
a brittle consumer-subscription scraper
a general automation system with unrestricted machine access
a marketplace before security and permissioning are mature
```

The first version should also not hide too much logic behind opaque abstractions. The agent should be able to inspect and reason about the runtime.

## 6. External landscape and rationale

OpenAI Codex CLI is a useful reference because it is local, terminal-native, can read/change/run code in the selected directory, is open source, is built in Rust, and supports both ChatGPT sign-in and API-key authentication. Its quickstart also describes Agent mode as the default mode that can read files, run commands, and write changes in a project directory. This validates the local terminal coding-agent direction and the value of subscription-backed delegated agent support. ([OpenAI Developers][1])

The public Terminal-Bench 2.0 leaderboard currently shows Codex GPT-5.5 at 82.0% ± 2.2 and Simple Codex GPT-5.3-Codex at 75.1% ± 2.4. This does not prove one public implementation is universally best, but it is strong evidence that high-quality harnessing around coding/terminal tasks matters. ([Terminal-Bench][2])

OpenAI’s article on the Codex agent loop gives several design lessons that should influence this project: context window management is a core agent responsibility; tool schemas, environment messages, permissions, and instructions are part of prompt construction; changing tools or configuration mid-run can harm prompt caching; and compaction becomes necessary when long runs approach context limits. ([OpenAI][3])

OpenAI’s Agents SDK direction is also relevant. The Python SDK is positioned for code-first agent orchestration, tools, handoffs, state, tracing, guardrails, and sandbox execution. The TypeScript SDK is described as lightweight and built around a small set of primitives. This supports the decision to keep our own kernel small while making Python and TypeScript first-class. ([OpenAI Developers][4])

Pi’s TypeScript coding-agent extension model is a useful reference for extensibility. Its extensions can subscribe to lifecycle events, register LLM-callable tools, add commands, and hot reload from global or project-local extension directories. We should copy the spirit, not necessarily the exact API. ([GitHub][5])

OpenClaw and openclaw-code-agent validate always-on, multi-channel, delegated-agent operation. openclaw-code-agent runs Claude Code and Codex as managed background coding sessions from chat, keeps work isolated in git worktrees, and supports plan review, merge, or PR flows. ([GitHub][6])

Hermes Agent validates the self-improving and persistent-agent direction. Its positioning around persistent memory, generated skills, and running from server or cloud VM is directionally aligned with an always-on variant of this harness. ([GitHub][7])

Shopify’s Autoresearch work validates metric-driven agent loops beyond ML training. The core idea is to measure a baseline, propose a change, run an experiment, keep improvements, discard regressions, and repeat. This should become a workflow extension, not part of the minimal kernel. ([Shopify][8])

## 7. Architectural decision summary

The selected direction is:

```text
Python-first kernel
TypeScript-first extension and web/app surface
optional Rust executor later
bounded YOLO by default
tiny kernel, optimized flagship profile
provider-neutral raw model interface
delegated agent-provider interface for Codex CLI, Claude Code, Gemini CLI, OpenCode, and similar systems
event-sourced trace architecture
structured compression and retrieval
strong security boundary around workspace, secrets, network, and host mutation
evals from the beginning
```

The key tradeoff is intentional: we do not optimize the first version for the fastest binary or most polished terminal UX. We optimize it for harness iteration, trace review, profile tuning, and model inspectability.

## 8. High-level architecture

The system should be organized as:

```text
agentd
  core runtime
  model providers
  agent providers
  workspace manager
  executor interface
  policy engine
  event log
  profile loader
  context builder
  compression/retrieval
  extension host

agentctl
  CLI/TUI entrypoint
  run/eval/replay/config commands

profiles
  apex-coder
  research
  review
  local-small-model
  delegated-codex

packages/ts-sdk
  client API
  extension SDK
  UI bindings
  schema definitions

packages/web-ui
  browser UI
  trace viewer
  session control
  approval console

extensions
  autoresearch
  browser/research
  memory
  repo-map
  code-review
  pr-tools

executor-rs
  later hardened executor
  PTY support
  sandbox integration
  filesystem watching
  process control
```

A typical local coding run:

```text
user task
  -> agentctl starts run
  -> workspace manager creates or selects workspace
  -> profile builds initial context
  -> model provider produces tool call(s)
  -> policy checks tool call
  -> executor runs tool
  -> event log records result
  -> compressor/retriever updates working state
  -> verifier runs checks
  -> final diff/answer/report produced
```

A delegated agent run:

```text
user task
  -> kernel selects agent provider
  -> workspace manager creates worktree
  -> delegated provider starts Codex CLI / Claude Code / other agent
  -> logs and diffs are collected
  -> kernel summarizes result
  -> verifier checks workspace
  -> final answer/diff/PR produced
```

## 9. Kernel requirements

The kernel must be deliberately small. It should contain:

```text
run lifecycle
state object
model-call interface
tool-call dispatch
event logging
profile hook invocation
compression trigger
policy boundary
workspace registration
provider registry
extension registry
```

The kernel should not contain:

```text
complex search heuristics
benchmark-specific prompting
long coding policies
repo-map heuristics
semantic retrieval ranking
specialized autoresearch loops
domain-specific tools
UI logic
marketplace logic
```

The kernel should be boring and obvious.

The minimal loop should conceptually be:

```python
while not state.done:
    context = profile.build_context(state)
    response = model.complete(context, tools=profile.visible_tools(state))
    log.append(ModelResponse(response))

    for call in response.tool_calls:
        decision = policy.evaluate(call, state)
        log.append(PolicyDecision(decision))

        if decision.blocked:
            state.add_observation(decision.reason)
            continue

        result = executor.run(call, state)
        log.append(ToolResult(result))
        profile.after_tool_result(state, call, result)

    if profile.should_compact(state):
        state = compressor.compact(state)
        log.append(CompactionEvent(...))

    if profile.should_finish(state):
        state.done = True
```

This loop is the core product. It should remain legible.

## 10. Profile requirements

A profile is the primary capability surface.

The flagship profile should be called something like `apex-coder`. The name is less important than the role: it is the highly optimized default.

The profile owns:

```text
system/developer instruction text
tool selection
tool schema ordering
context packing
search policy
compression policy
verification policy
stopping policy
delegation policy
subagent policy
model-specific prompt adaptations
error recovery policy
task-class routing
"when to ask user" policy
```

The profile should be allowed to be opinionated. It should not be neutral.

Default taste for `apex-coder`:

```text
prefer acting over asking
prefer exact repo evidence over assumptions
prefer literal search before semantic search
prefer tests over speculation
prefer minimal patches over rewrites
prefer worktrees for risky changes
prefer running targeted checks early
prefer full traceability over hidden magic
prefer structured compression over prose summaries
prefer continuing until verified
prefer explicit uncertainty only when it affects outcome
prefer bounded YOLO over approval-heavy flow
```

This is where the engineering effort should concentrate. The kernel enables the profile; the profile wins.

## 11. Bounded YOLO execution

The default execution mode should be YOLO inside the workspace.

Allowed without approval:

```text
read files in workspace
write files in workspace
apply patches
run shell commands in workspace
inspect git diff/status/log
run tests, linters, typecheckers, builds
install project-local dependencies
create branches
create git worktrees
create commits if profile permits
run local repo search
use configured web/search tools
spawn bounded subagents
generate reports and artifacts
```

Blocked or escalated:

```text
write outside workspace
read high-risk secrets outside workspace
modify shell startup files
modify SSH keys, tokens, password stores, browser profiles
delete large directory trees outside workspace
deploy to production
spend money
mutate cloud infrastructure
publish packages
push to remote without explicit policy
exfiltrate files
change global OS configuration
install system-level packages unless explicitly allowed
```

The default should feel uninterrupted. The agent should not ask before routine coding operations. The user should experience a capable agent that acts.

The security boundary is the workspace. YOLO is absence of interruption inside the chosen trust boundary, not absence of policy.

## 12. Workspace model

The workspace manager should support these levels:

```text
1. Existing directory
2. Git worktree
3. Containerized workspace
4. Remote sandbox
5. Cloud worker
```

The default should be a git worktree when the repo is under git. This gives cheap isolation and easy rollback.

Workspace state should include:

```text
root path
git root
branch/worktree name
allowed write paths
network mode
environment variables policy
secrets policy
tool permissions
command history
file snapshots if needed
current diff
final artifact paths
```

The agent should produce explicit end-of-run artifacts:

```text
run.jsonl
summary.md
final.diff
metrics.json
artifacts/
  command-output-001.txt
  context-snapshot-001.txt
  file-snapshot-001.txt
```

## 13. Event log and replay

Every meaningful action must become an event.

Core event types:

```text
RunStarted
UserTaskReceived
ContextBuilt
ModelRequest
ModelResponse
ToolCallRequested
PolicyDecision
ToolCallStarted
ToolCallFinished
FileRead
PatchApplied
CommandStarted
CommandFinished
DiffSnapshot
CompactionStarted
CompactionFinished
VerifierStarted
VerifierFinished
DelegatedAgentStarted
DelegatedAgentFinished
ExtensionLoaded
ExtensionAction
RunFinished
RunFailed
```

Events should be stored as JSONL. The event log should be the source of truth.

A good event object:

```json
{
  "id": "evt_...",
  "run_id": "run_...",
  "type": "CommandFinished",
  "time": "2026-04-23T12:00:00Z",
  "parent_event_id": "evt_...",
  "data": {
    "cmd": "pytest tests/test_parser.py",
    "cwd": "/repo",
    "exit_code": 1,
    "duration_ms": 4182,
    "stdout_excerpt": "...",
    "stderr_excerpt": "...",
    "full_output_artifact": "artifacts/cmd-004.txt"
  }
}
```

The replay tool should allow engineers to inspect:

```text
exact context sent to model
tool schema shown to model
tool calls made
command outputs
diffs after each edit
compaction summaries
final state
why the agent stopped
```

This is mandatory for serious harness optimization.

## 14. Context construction

The context builder is one of the most important parts of the system.

It should construct context in stable layers:

```text
1. Static profile instructions
2. Tool schemas
3. Environment and workspace boundary
4. User task
5. Repo metadata
6. Relevant files/snippets
7. Current structured state
8. Recent event excerpts
9. Retrieved artifacts
10. Verification status
11. Open issues and next action
```

Static content should be placed early and remain stable where provider caching benefits from exact prefix reuse. Variable run-specific content should be placed later. This aligns with the general lesson from Codex’s agent-loop writeup that changing tools/configuration mid-run can harm caching, and that compaction is needed when context grows too large. ([OpenAI][3])

The context builder should avoid dumping entire files or entire command logs by default. It should include enough to act, and store the rest as retrievable artifacts.

Context snapshots should be stored for replay.

## 15. Compression strategy

Compression should not be vague chat summarization. It should be structured state extraction.

A compressed state should contain:

```yaml
objective: ...
user_constraints: ...
workspace:
  root: ...
  branch: ...
files_inspected:
  - path: ...
    reason: ...
    key_findings: ...
files_modified:
  - path: ...
    changes: ...
commands_run:
  - cmd: ...
    result: ...
    relevance: ...
tests:
  passed: ...
  failed: ...
  unresolved: ...
known_facts:
  - ...
hypotheses:
  - ...
decisions:
  - ...
open_issues:
  - ...
next_actions:
  - ...
artifacts:
  - id: ...
    type: ...
    description: ...
```

The exact event log remains outside context. Compression is for working memory, not auditability.

Compression should trigger based on:

```text
token pressure
large command output
many tool calls
phase transition
before delegation
before long-running subtask
before final verification
```

## 16. Retrieval and search

Search should be layered.

Layer 1: deterministic file/repo search.

```text
rg
fd
git grep
file tree
package metadata
test names
docs names
```

Layer 2: code-aware search.

```text
symbols
definitions
imports
references
AST chunks
call graph if cheap
```

Layer 3: semantic search.

```text
embedding index over files
embedding index over docs
embedding index over prior traces
memory retrieval
```

Layer 4: external search.

```text
official docs
package docs
release notes
issue trackers
web search
```

Default coding policy:

```text
1. Inspect repo structure.
2. Search exact names from the user request.
3. Search tests before implementation when possible.
4. Inspect likely implementation files.
5. Patch minimally.
6. Run targeted checks.
7. Broaden checks if needed.
8. Use semantic or web search only when literal repo evidence is insufficient.
```

Literal search should beat semantic search for named code entities. Semantic search is useful when the agent does not know the exact name.

## 17. Tool design

The initial tool set should be small and high-leverage:

```text
shell(cmd, cwd?, timeout?, env?)
read_file(path, offset?, limit?)
list_files(glob?, limit?)
apply_patch(patch)
write_file(path, content)
search_repo(query, mode?)
git_status()
git_diff(path?)
spawn_agent(task, scope?, profile?)
web_search(query)          optional
fetch_url(url)             optional
finish(summary)
```

Tools should be deterministic where possible. Tool result formatting should be optimized for model usefulness.

Shell output should be summarized but preserved:

```text
return exit code
return duration
return concise stdout/stderr excerpt
store full output as artifact
detect common error classes
suggest retrieval command for full output if needed
```

The profile should be responsible for deciding when a tool is visible. Tool lists should be stable during runs when possible.

## 18. Editing strategy

The default should prefer patch-based edits.

Editing sequence:

```text
1. Search relevant locations.
2. Read relevant snippets.
3. Apply minimal patch.
4. Inspect diff.
5. Run targeted verification.
6. Repair if needed.
7. Broaden verification.
8. Final diff check.
```

Full-file rewrite is allowed for:

```text
generated files
very small files
explicit rewrites
scaffold generation
files where patching is less reliable
```

The agent should avoid broad refactors unless the task requires them.

## 19. Verification strategy

Verification should be aggressive and concrete.

After meaningful edits:

```text
run targeted tests
run typecheck/lint/build if obvious
inspect failure output
repair
rerun
inspect git diff
ensure no unrelated file changes
check original task against final state
```

Pre-final checklist:

```text
Original task satisfied?
Changed files expected?
Tests/checks run?
Failures remaining?
Unrelated diffs?
Risky behavior?
Need to mention uncertainty?
```

The agent should not finish merely because it has made a plausible edit. It should finish because it has verified or exhausted reasonable verification options.

## 20. Provider architecture

There should be two provider classes.

Model providers expose raw model calls:

```text
OpenAI API
Anthropic API
Gemini API
OpenRouter
local OpenAI-compatible endpoint
Ollama/vLLM/LM Studio
custom enterprise endpoint
```

Agent providers expose delegated external harnesses:

```text
Codex CLI
Claude Code
Gemini CLI
OpenCode
other coding agents
```

This distinction is critical.

Raw model providers are used when our harness owns the loop.

Agent providers are used when another harness owns the loop and we delegate a task to it.

This lets us support official subscription-backed clients without pretending a consumer subscription is equivalent to a raw API key. For example, Codex can be integrated as an external agent provider through official CLI authentication, while direct OpenAI model calls use API credentials. Codex’s official authentication docs distinguish ChatGPT sign-in for subscription access from API-key usage for usage-based access. ([OpenAI Developers][9])

Provider capabilities should be explicit:

```yaml
tool_calling: true
parallel_tool_calls: true
structured_output: true
vision: true
reasoning_effort: ["low", "medium", "high"]
prompt_cache: true
max_context_tokens: 200000
max_output_tokens: 32000
supports_native_web_search: true
supports_images: true
supports_computer_use: false
cost_model: ...
```

The harness should not flatten all models into the same interface behaviorally. It should expose a common API, but allow model-specific profiles.

## 21. TypeScript SDK and extension surface

TypeScript is important for:

```text
webapp embedding
npm package distribution
extension authoring
browser UI
frontend/backend apps
user community adoption
```

The TypeScript SDK should provide:

```typescript
registerTool(...)
registerCommand(...)
on("turn_start", ...)
on("before_tool_call", ...)
on("after_tool_call", ...)
on("context_build", ...)
on("compact", ...)
emit(...)
getState(...)
setSessionData(...)
```

The TypeScript SDK should communicate with `agentd` through a language-neutral protocol such as JSON-RPC, WebSocket, or local HTTP.

The extension protocol should not be TypeScript-only. Python extensions should also be supported.

Extension manifest:

```yaml
name: autoresearch
version: 0.1.0
runtime: python | node
permissions:
  filesystem: workspace
  shell:
    allow:
      - pytest
      - python
      - npm
  network: false
hooks:
  - command:/autoresearch
  - after_tool_call
tools:
  - run_experiment
  - compare_metric
commands:
  - autoresearch
```

Extensions should be able to:

```text
register tools
register slash commands
subscribe to lifecycle hooks
add context snippets
add retrieval sources
add verification steps
store scoped state
request permissions
define workflows
```

Extensions should not be able to silently mutate core policy or escalate permissions.

## 22. Self-extension policy

The system should support self-extension, but extension loading must be explicit and controlled.

Allowed:

```text
agent writes a candidate extension
agent writes tests for the extension
agent proposes manifest
kernel validates manifest
extension runs in workspace or extension sandbox
extension is loaded after policy check
```

Not allowed:

```text
silent privilege escalation
modifying core kernel without trace
loading arbitrary code from web without review
granting host-wide file access by default
bypassing command policy
```

Self-extension should feel powerful, but should remain auditable.

## 23. Autoresearch as a workflow extension

`/autoresearch` should be implemented as an extension, not kernel behavior.

Generic loop:

```text
1. Create isolated worktree.
2. Measure baseline.
3. Ask agent for one hypothesis.
4. Apply patch.
5. Run metric command.
6. Run invariant checks.
7. If metric improves and invariants pass: commit.
8. Otherwise: revert.
9. Record lesson.
10. Repeat until budget exhausted.
```

Required inputs:

```text
objective
metric command
optimization direction
budget
invariant commands
allowed files
stop conditions
variance policy
```

Example:

```bash
agent /autoresearch \
  --metric "python bench.py --json" \
  --objective "minimize latency" \
  --budget 50 \
  --invariant "pytest"
```

Autoresearch must defend against metric gaming. It should separate optimization metrics from invariant checks and avoid letting the agent simply alter the metric script unless explicitly allowed.

## 24. Always-on mode

Always-on should be a later mode built on the same kernel, not a separate product.

Always-on requires a control plane:

```text
session manager
queue
identity
approvals
notifications
workspace lifecycle
scheduled jobs
credential policy
memory
audit log
```

Control plane and execution plane should be separated.

Execution plane:

```text
runs commands
edits files
reads repos
calls tools
creates diffs
executes subagents
```

Control plane:

```text
decides what jobs exist
owns user identity
owns notification surfaces
owns schedules
owns permissions
owns approvals
owns task queue
owns long-term memory policy
```

Always-on without permissions and auditability is dangerous. This should be developed after the local YOLO harness is stable.

## 25. Security model

Security must start in version zero because YOLO plus self-extension plus always-on is high authority.

Default principles:

```text
workspace-first
deny host-wide mutation
explicit network modes
secret redaction
no silent exfiltration
extension permissions
trace all side effects
separate control plane from execution plane
support containers/worktrees
treat generated extensions as untrusted until validated
```

Policy should evaluate:

```text
path access
command risk
network access
environment variable exposure
secret-like output
large deletion
remote push/deploy/publish
credential access
extension permission request
delegated agent permissions
```

Policy decisions:

```text
allow
allow_with_redaction
allow_in_sandbox
deny
require_user_approval
```

YOLO default maps many workspace operations to `allow`, but external-boundary operations still get blocked or escalated.

## 26. Evaluation strategy

Evals should exist from the beginning.

Evaluation layers:

```text
1. Unit tests for kernel
2. Golden traces for profile behavior
3. Local coding tasks
4. Repo-specific regression tasks
5. Terminal-Bench/Harbor adapter
6. Autoresearch benchmarks
7. Long-horizon tasks
8. Delegated-agent comparisons
```

Metrics:

```text
success rate
task completion
test pass rate
hidden-test proxy
number of tool calls
wall time
model cost
context tokens
compaction count
failure mode
unrelated diff count
user intervention count
replayability
```

Every profile change should be evaluated against a stable task set.

A profile version report should look like:

```text
apex-coder v0.4
  success: 68%
  avg tool calls: 44
  avg cost: 0.69
  avg wall time: 8m
  regressions:
    - task_017: stopped early
    - task_031: overused semantic search
  improvements:
    - task_009: fixed after targeted test policy
```

## 27. Observability and trace viewer

The trace viewer should become an internal power tool.

It should show:

```text
timeline of events
context snapshots
model requests
tool schemas
tool calls
shell commands
command outputs
diffs over time
compactions
verification results
cost/token usage
stop reason
failure classifications
```

This is not optional. Harness quality depends on seeing how runs fail.

## 28. Project structure

Recommended initial repository layout:

```text
agent-harness/
  pyproject.toml
  README.md
  docs/
    DESIGN.md
    SECURITY.md
    PROVIDERS.md
    EXTENSIONS.md
    EVALS.md

  agentd/
    __init__.py
    kernel.py
    state.py
    events.py
    models/
      base.py
      openai_provider.py
      anthropic_provider.py
      openrouter_provider.py
      local_provider.py
    agent_providers/
      base.py
      codex_cli.py
      claude_code.py
      gemini_cli.py
      opencode.py
    tools/
      base.py
      shell.py
      files.py
      patch.py
      git.py
      search.py
      web.py
    workspace/
      base.py
      existing.py
      git_worktree.py
      container.py
    policy/
      engine.py
      rules.py
      secrets.py
      commands.py
    context/
      builder.py
      repo_map.py
      retrieval.py
      compression.py
    profiles/
      loader.py
      schema.py
    extensions/
      host.py
      manifest.py
      python_runtime.py
      node_runtime.py
    tracing/
      log.py
      artifacts.py
      replay.py

  agentctl/
    cli.py
    commands/
      run.py
      eval.py
      replay.py
      config.py
      providers.py

  profiles/
    apex-coder/
      profile.yaml
      system.md
      context.py
      compress.py
      verify.py
      search.py
      tools.py
      model_profiles/
        gpt.yaml
        claude.yaml
        gemini.yaml
        local.yaml

  extensions/
    autoresearch/
      manifest.yaml
      extension.py
      tests.py
    memory/
    browser/
    pr_review/

  packages/
    ts-sdk/
      package.json
      src/
        client.ts
        extension.ts
        schema.ts
        events.ts
    web-ui/
      package.json
      src/

  executor-rs/
    Cargo.toml
    src/

  evals/
    tasks/
    runners/
    reports/
```

## 29. Initial milestones

Milestone 0: Skeleton

```text
repo structure
CLI run command
event log
shell/read/apply_patch tools
OpenAI-compatible model provider
basic workspace
minimal profile
```

Milestone 1: Local YOLO coder

```text
git worktree workspace
bounded command/path policy
repo search
structured context builder
patch-based editing
targeted verification loop
run artifacts
replay command
```

Milestone 2: Apex profile v0

```text
optimized system prompt
search policy
compression policy
verification policy
context snapshots
model profile variants
first local eval suite
```

Milestone 3: Provider expansion

```text
Anthropic/Gemini/OpenRouter/local providers
Codex CLI delegated provider
Claude Code delegated provider
capability matrix
cost/token accounting
```

Milestone 4: Extension system

```text
manifest schema
Python extension runtime
TypeScript extension SDK
lifecycle hooks
slash commands
extension permissions
```

Milestone 5: Autoresearch

```text
worktree experiment loop
baseline measurement
metric/invariant separation
keep/revert commits
variance handling
run reports
```

Milestone 6: Trace viewer and evals

```text
web trace viewer
eval runner
profile comparison reports
failure taxonomy
benchmark adapters
```

Milestone 7: Always-on prototype

```text
control plane
job queue
notification surface
approval console
session memory
remote workspace support
```

## 30. Engineering principles

Build the smallest loop that can improve itself.

Do not hide behavior behind framework abstractions.

Make every side effect traceable.

Make workspace operations uninterrupted.

Make external-boundary operations explicit.

Treat the default profile as the product.

Keep provider interfaces honest.

Prefer replayable experiments over vibes.

Prefer structured state over chat history.

Prefer fewer, stronger tools over many weak tools.

Prefer modularity that improves the agent’s understanding, not modularity for its own sake.

## 31. Open questions

```text
Should the first UI be CLI-only, or should trace viewer land very early?

Should the Python kernel expose JSON-RPC from day one?

Which provider should be the first non-OpenAI raw model provider?

How strict should default network access be?

Should commits be automatic in YOLO mode or only diffs?

Should delegated agents be allowed to run fully YOLO by default?

Should extension loading require local signature/trust metadata?

How much of the profile should be Python code versus declarative YAML/Markdown?

Should semantic search be built in early, or delayed until literal/code-aware search is strong?
```

## 32. Decision to execute

Build the Python kernel now.

Keep it tiny.

Make `apex-coder` the default.

Make YOLO-in-workspace the default.

Make TypeScript a first-class SDK.

Add delegated Codex/Claude Code support as separate agent providers.

Do not let provider neutrality weaken the optimized default profile.

Do not let extensibility bloat the kernel.

Do not treat traces/evals as optional.

The intended end state is a harness that remains small enough to understand, but strong enough to outperform larger systems through better context, better tools, better compression, better verification, and better optimization discipline.

[1]: https://developers.openai.com/codex/cli?utm_source=chatgpt.com "Codex CLI"
[2]: https://www.tbench.ai/leaderboard/terminal-bench/2.0 "Terminal-Bench"
[3]: https://openai.com/index/unrolling-the-codex-agent-loop/ "Unrolling the Codex agent loop | OpenAI"
[4]: https://developers.openai.com/api/docs/guides/agents "Agents SDK | OpenAI API"
[5]: https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/extensions.md "pi-mono/packages/coding-agent/docs/extensions.md at main · badlogic/pi-mono · GitHub"
[6]: https://github.com/goldmar/openclaw-code-agent "GitHub - goldmar/openclaw-code-agent · GitHub"
[7]: https://github.com/nousresearch/hermes-agent "GitHub - NousResearch/hermes-agent: The agent that grows with you · GitHub"
[8]: https://shopify.engineering/autoresearch "Autoresearch isn’t just for training models (2026) - Shopify"
[9]: https://developers.openai.com/codex/auth?utm_source=chatgpt.com "Authentication – Codex | OpenAI Developers"
