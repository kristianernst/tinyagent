# tinyagent Agentic Capability Plan

Status: structured approach draft
Source: docs/comment-on-update.md
Sandbox reference: https://cursor.com/blog/agent-sandboxing
Workflow: Graphite stacked branches, each branch reviewable on its own

## 1. Direction

The latest review says tinyagent does not need a larger agent framework. It
needs harder runtime invariants and better recovery surfaces:

- every workspace mutation is detected, regardless of which tool caused it
- worktree isolation is named honestly and separated from real sandboxing
- shell failures explain policy and sandbox constraints in model-visible terms
- model/provider specs choose familiar edit tools and context budgets
- ContextFS becomes the universal recovery surface for history, tools, diffs,
  failures, observations, and terminal output
- runs can be streamed, reconnected, replayed, inspected, forked, approved, and
  rendered by clients
- evals compare harness variants and explain what changed

The core loop should stay small. The visible workflow should stay lightweight.
The hardening belongs in evidence, execution boundaries, context, model
adaptation, session state, and eval feedback.

## 2. Current Baseline

Several primitives from the older plan already exist and should be extended
rather than re-created:

- `agentd/transcript.py` records model responses, tool calls, tool results,
  finish-gate items, and compactions.
- `agentd/observations.py` extracts basic typed observations from shell and
  patch results.
- `ApexCoderProfile.plan_next_context(...)` already chooses simple context
  modes.
- `agentd/progress.py` blocks repeated failed commands and repeated patch
  failures.
- `agentd/execution.py` defines local `ExecutionEnvelope` metadata.
- `agentd/models.py` defines `ModelCapabilities`.
- `agentd/extensions.py` provides a small extension host.
- `agentd/eval_metrics.py` derives initial harness metrics from events.

The main gaps are that the existing pieces are not yet strong enough:

- mutation events are planned/completed around `shell` and `apply_patch`, but
  they do not prove the workspace actually changed
- the finish gate still keys edits primarily off `apply_patch`
- `read_file` and `search_repo` are registered but hidden by the default
  profile
- worktree mode is exposed as a sandbox mode even though it is only git
  isolation
- there is no real `container` or native sandbox backend
- sandbox/policy failures are not yet rendered as rich capability failures
- `ModelCapabilities` does not yet describe edit style, provider protocol, or
  prompt/tool variants
- ContextFS is useful but still sparse
- there is no `agentctl serve` runtime surface
- evals report one run but do not compare named harness variants

## 3. Sandbox Lessons To Apply

Cursor's sandboxing writeup makes three points that should shape tinyagent:

1. Approval prompts are not enough. Frequent approvals cause fatigue, especially
   when users run multiple agents in parallel. The useful model is free action
   inside a constrained environment and explicit approval only when crossing a
   boundary such as network access.
2. The sandbox API should be uniform even when implementation is platform
   specific. Cursor uses different primitives on each OS: Seatbelt via
   `sandbox-exec` on macOS, Landlock and seccomp on Linux, and Linux sandboxing
   inside WSL2 on Windows.
3. The harness must teach the model what the sandbox permits. Shell tool
   descriptions should state filesystem, git, and network constraints, and
   failed shell results should name the responsible constraint instead of
   returning a generic command failure.

tinyagent should not jump straight to a complex native sandbox. It should first
separate the execution contract from the backend, then add one real enforced
backend, then make the shell prompt/results sandbox-aware.

## 4. Stack Shape

Use Graphite for implementation work. Prefer stacked PRs over one large branch
or unrelated flat branches, and keep each stack entry independently reviewable.

Recommended main stack:

```bash
gt checkout main
gt create ta-agentic-plan -a -m "Update agentic capability plan"
gt create ta-visible-inspection --onto ta-agentic-plan -m "Expose structured inspection tools"
gt create ta-workspace-delta --onto ta-visible-inspection -m "Detect workspace mutations around tool calls"
gt create ta-sandbox-contract --onto ta-workspace-delta -m "Separate sandbox contract from worktree isolation"
gt create ta-model-specs --onto ta-sandbox-contract -m "Select tool shapes from model specs"
gt create ta-contextfs-recovery --onto ta-model-specs -m "Expand ContextFS recovery files"
gt create ta-runtime-serve --onto ta-contextfs-recovery -m "Add run server and SSE event stream"
gt create ta-eval-compare --onto ta-runtime-serve -m "Compare harness variants in evals"
```

Recommended side stack:

```bash
gt create ta-container-sandbox --onto ta-sandbox-contract -m "Add first enforced sandbox backend"
```

`ta-container-sandbox` depends on the sandbox contract, but it should not block
model specs, ContextFS, runtime server, or eval comparison. Docker/Podman work
is platform-sensitive and should mature independently while the main harness
stack keeps moving.

Run the fast suite after each implementation branch:

```bash
PYTHONPATH=. pytest
```

Before publishing the stack:

```bash
git status
git diff
PYTHONPATH=. pytest
gt submit --stack --dry-run
```

## 5. Phase 0: Planning

Branch: `ta-agentic-plan`

Purpose: replace the older pro-update implementation plan with this current
roadmap based on `docs/comment-on-update.md` and Cursor's sandboxing article.

Acceptance criteria:

- `docs/plan.md` names the updated priorities and current baseline.
- The sandbox plan distinguishes worktree isolation from real sandboxing.
- No runtime code changes are included in this documentation branch.

Verification:

```bash
git diff -- docs/plan.md
```

## 6. Phase 1: Visible Structured Inspection

Branch: `ta-visible-inspection`

Purpose: give the model structured read/search affordances without adding
workflow structure.

Changes:

- Change `ApexCoderProfile.DEFAULT_VISIBLE_TOOL_NAMES` from
  `("shell", "apply_patch")` to at least
  `("read_file", "search_repo", "apply_patch", "shell")`.
- Keep `list_files` optional; `rg --files` through shell remains fine.
- Update `profiles/apex-coder/system.md` so inspection prefers `read_file` and
  `search_repo`, while shell remains the default for tests, builds, git, and
  arbitrary developer commands.
- Add observation extraction for `read_file` and `search_repo` results rather
  than only shell `rg` commands.
- Return richer `ToolResult` metadata for structured inspection:
  - `read_file` should emit path, line range, total lines, byte count, and
    `artifact_path`/`read_hints` when a successful read is large enough to need
    artifact backing.
  - `search_repo` should set `artifact_path` and `read_hints` for captured
    search output, not only store artifact paths in `data`.
- Add observations:
  - `read_file -> file_read`
  - `search_repo -> search_result`
- Update `agentd/observations.py`, `agentd/eval_metrics.py`, and
  `agentd/context/checkpoint.py` so structured inspection counts as inspection
  and context evidence.
- Treat `file.read` and `search.completed` events as pre-edit inspection
  evidence in eval metrics.

Acceptance criteria:

- Registered hidden tools still cannot be called unless visible in the model
  request.
- Structured search/read outputs stay small and artifact-backed when needed.
- Finish and eval gates recognize both shell inspection and first-party
  inspection tools.
- `read_file -> apply_patch -> final` satisfies inspect-before-edit, but still
  requires diff/file inspection and verification after the edit.

Tests:

- Default profile exposes `read_file`, `search_repo`, `apply_patch`, and
  `shell`.
- Hidden `list_files` remains blocked unless explicitly visible.
- `read_file` before `apply_patch` satisfies the inspect-before-edit metric.
- `search_repo` emits a `search_result` observation.
- Large successful `read_file` and `search_repo` results provide artifact paths
  and read hints.

## 7. Phase 2: Workspace Delta Observer

Branch: `ta-workspace-delta`

Purpose: make mutation tracking evidence-based instead of tool-name-based.

Changes:

- Add `WorkspaceDeltaObserver`, likely in `agentd/workspace_delta.py`.
- Snapshot cheap workspace state before and after every allowed tool call:
  - `git status --porcelain=v1 -z`
  - `git diff --name-only -z HEAD --`
  - `git diff --stat HEAD --`
  - `git ls-files --others --exclude-standard -z`
- Exclude tinyagent-owned and VCS paths from all mutation detection:
  - `.git/`
  - `.tinyagent/`
  - `state.output_dir`
  - configured generated artifact directories, if any
- For non-git workspaces, maintain a manifest of
  `path -> size, mtime_ns, mode`, then hash only files whose stat changed.
  Do not use a sample-based detector that can miss changes.
- Emit:
  - `workspace.delta.started`
  - `workspace.delta.completed`
  - `workspace.mutation.detected`
  - `file.changed`
  - `diff.snapshot`
- Write mutation diffs to artifacts such as
  `context/diffs/mutation-0003.patch`.
- Append `file_changed` and `diff_seen` observations from detected deltas,
  independent of whether the mutating tool was `apply_patch`, `shell`, or an
  extension tool.
- Change finish gates from "after successful apply_patch" to "after any
  detected workspace mutation."
- Keep existing `patch_applied` observations, but treat them as one source of
  mutation evidence, not the source of truth.
- Split implementation into two commits inside the branch:
  - delta observer, events, observations, and artifacts
  - finish-gate migration from `apply_patch` evidence to mutation evidence
- Handle verification commands that mutate files without creating a verification
  loop. If the last mutation was caused by a verification command, require
  post-mutation diff/file inspection. Require another verification only after a
  later non-verification mutation.

Acceptance criteria:

- Shell commands that mutate files require post-mutation diff/file inspection
  and verification before final answer.
- Non-mutating shell commands do not trigger edit gates.
- Non-git workspaces still detect changes well enough to force changed-file
  inspection.
- Mutation artifacts are recoverable through ContextFS.
- ContextFS and run artifact writes do not themselves count as workspace
  mutations.

Tests:

- `python -c 'open("x.txt","w").write("x")'` triggers
  `workspace.mutation.detected`.
- `pytest` or `rg` without file changes does not trigger mutation.
- A shell mutation followed by final answer is blocked until diff/file
  inspection and verification evidence exists.
- Non-git workspace mutation produces changed-file evidence.
- ContextFS refresh after a read-only command does not trigger mutation gates.
- Snapshot-test or generated-file mutation from a verification command requires
  diff/file inspection, but not another verification unless source edits follow.

## 8. Phase 3: Sandbox Contract

Branch: `ta-sandbox-contract`

Purpose: make execution boundaries explicit before adding a real sandbox.

Changes:

- Replace `SandboxMode = Literal["none", "worktree"]` with a clearer split:
  - `workspace_mode = current | worktree | auto`
  - `sandbox_mode = none | container | native`
  - optionally keep `worktree` as a deprecated CLI alias that maps to
    `workspace_mode=worktree` and `sandbox_mode=none`
- Model separate concepts explicitly:
  - `WorkspaceMode = Literal["auto", "current", "worktree"]`
  - `SandboxMode = Literal["none", "container", "native"]`
  - `NetworkMode = Literal["deny", "ask", "allow"]`
  - `SandboxBackend = Literal["none", "docker", "podman", "seatbelt",
    "landlock_seccomp", "wsl2"]`
- Update `WorkspaceEnvelope` so `sandbox_enforced` is true only when a real
  sandbox backend enforces filesystem/process/network boundaries.
- Expand `ExecutionEnvelope` with:
  - read roots
  - write roots
  - denied paths
  - network mode
  - git access mode
  - escalation hint
  - backend name and version
- Update shell tool descriptions to tell the model what filesystem, git, and
  network permissions are available in the current envelope.
- Standardize failure metadata as multiple dimensions rather than one flat
  string:

```json
{
  "failure_kind": "sandbox_blocked",
  "capability": "network",
  "source": "sandbox",
  "recoverability": "request_approval"
}
```

- Use the dimensions consistently:
  - `policy_denied + capability=network + source=policy`
  - `sandbox_blocked + capability=network + source=sandbox`
  - `sandbox_blocked + capability=filesystem + source=sandbox`
  - `command_failed + capability=process + source=tool`
- Render sandbox failures as capability failures, for example:
  `sandbox blocked command: network denied. Request approval or choose an
  offline path.`

Acceptance criteria:

- Worktree mode is no longer described as a real sandbox.
- Existing local shell behavior remains unchanged in `sandbox_mode=none`.
- Policy-denied and sandbox-blocked results are distinguishable in events,
  observations, metrics, and final-answer gates.
- Shell output gives the model enough information to recover from denied
  capabilities.
- `worktree` is removed as an internal sandbox mode, except for an explicit CLI
  migration alias if kept.

Tests:

- CLI accepts `none`, `container`, and `native` sandbox modes and rejects
  unsupported combinations clearly.
- Deprecated `--sandbox-mode worktree`, if kept, warns or maps predictably.
- Shell result metadata includes envelope capabilities.
- Policy denial and synthetic sandbox denial produce different observations,
  failure sources, capabilities, and recoverability hints.

## 9. Phase 4: Model Specs And Edit Adapters

Branch: `ta-model-specs`

Purpose: use model/provider knowledge to expose familiar tool shapes and budget
context correctly.

Changes:

- Keep `ModelCapabilities`, and add `ModelSpec` beside it rather than mutating
  the existing dataclass aggressively:

```python
@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    protocol: Literal["chat_completions", "responses", "anthropic", "gemini"]
    edit_style: Literal["apply_patch", "str_replace", "whole_file"]
    prompt_variant: str = "default"
    tokenizer: str = "heuristic"
    capabilities: ModelCapabilities = ModelCapabilities()
```

- Include:
  - model
  - provider
  - protocol: `chat_completions | responses | anthropic | gemini`
  - edit style: `apply_patch | str_replace | whole_file`
  - parallel tool support
  - reasoning support
  - prompt-cache support
  - context window
  - output limit
  - tokenizer
  - prompt variant
- Add edit tools:
  - `apply_patch`: patch grammar, rollback, path-safe
  - `str_replace_edit`: `old_str`/`new_str`, require unique match, rollback,
    path-safe
  - `write_file`: full overwrite, size cap, path-safe, generated or small files
    only by default
- Keep `apply_patch` as the OpenAI/Codex-like default.
- Let the profile choose visible edit tools from the spec:
  - OpenAI/Codex-like: `read_file`, `search_repo`, `apply_patch`, `shell`
  - Claude-like: `read_file`, `search_repo`, `str_replace_edit`, `shell`
  - Generic: `read_file`, `search_repo`, `write_file`, `shell`
- Do not expose multiple primary edit tools by default.
- Make token budgeting provider-aware where practical, replacing rough
  character division with model-specific counters when available.

Acceptance criteria:

- The kernel remains provider-agnostic.
- Provider-specific serialization and payload quirks stay in providers.
- The model sees only one primary edit tool by default.
- Unsupported provider/tool combinations fail clearly.

Tests:

- Fake OpenAI-like model sees `apply_patch`.
- Fake Claude-like model sees `str_replace_edit`.
- Provider without tool support fails before model call when visible tools are
  requested.
- Context budget uses the selected spec's context and output limits.
- If the selected spec exposes `str_replace_edit` and the model calls
  `apply_patch`, the call is blocked as hidden.

## 10. Phase 5: ContextFS Recovery Surface

Branch: `ta-contextfs-recovery`

Purpose: make files the universal recovery and discovery primitive.

Changes:

- Expand ContextFS with:
  - `context/INDEX.md`
  - `context/task.md`
  - `context/current_status.md`
  - `context/current_diff.patch`
  - `context/last_failure.md`
  - `context/observations.md`
  - `context/transcript.md`
  - `context/history/raw.jsonl`
  - `context/history/summary.md`
  - `context/tools/INDEX.md`
  - `context/tools/<tool>.md`
  - existing `context/shell/*.txt` tool output files
  - `context/diffs/<mutation>.patch`
- Do not add `context/terminal/<session>.txt` until there is a real persistent
  terminal/session abstraction.
- Add a safe first-party mechanism for model recovery reads:
  - either `read_context(path)`
  - or `ReadFileTool(allow_context_artifacts=True)`
- Strictly allow only intended recovery files, such as:
  - `context/**`
  - `artifacts/context-checkpoint-*.md`
  - selected tool output artifacts when referenced by ContextFS
- Do not expose raw internal artifacts by default:
  - `model-request-http-*.json`
  - `model-response-*.json`
  - `events.jsonl`, unless intentionally exposed through ContextFS
  - `metrics.json`, unless intentionally exposed through ContextFS
- Move long tool examples and capability explanations out of the static prompt
  and into `context/tools/*.md`.
- Change context building to inject a concise ContextFS index and fewer large
  recent tool previews.
- Add optional LLM compaction as a single `Compactor` interface. Keep the
  deterministic compactor as the default fallback.
- Use structured handoff sections for LLM compaction:
  Active Task, Goal, Constraints, Completed Actions, Active State, Blockers,
  Key Decisions, Pending User Asks, Relevant Files, Remaining Work, and
  Critical Context.

Acceptance criteria:

- A model can recover the latest task, diff, failure, observations, and
  transcript from files.
- Long outputs stay artifact-backed and are not pasted into event payloads.
- Context reports explain included and excluded items.
- Compaction output is framed as reference material, not as new instructions.
- ContextFS files intended for recovery are readable through the safe
  first-party mechanism without opening all run artifacts.

Tests:

- ContextFS writes all expected files during a run.
- `context/observations.md` includes mutation, verification, policy, and
  sandbox evidence.
- `context/transcript.md` preserves tool call/result pairing.
- Compaction references raw history and preserves the latest user ask.
- The model can read `context/INDEX.md`, `context/current_diff.patch`,
  `context/observations.md`, `context/transcript.md`, and `context/tools/*.md`.
- The model cannot read raw model request/response artifacts through the
  ContextFS reader unless explicitly allowed.

## 11. Phase 6: Runtime Server And UI State

Branch: `ta-runtime-serve`

Purpose: expose the existing event log as a live runtime for clients without
turning the kernel into a UI framework.

Changes:

- Add `agentctl serve`.
- Add a small runtime layer:
  - `RunStore` for durable events/artifacts
  - `RunBus` for live subscribers
  - `RunController` for start/cancel/approve/fork
  - `SessionStore` only if needed for branchable sessions
- Name v1 semantics precisely:
  - reconnectable UI, not resumable agent execution after process death
  - forkable runs, not full thread branching
  - approval broker, not just an HTTP endpoint
- Add an `ApprovalBroker` so the kernel can block on approval while HTTP
  requests resolve pending approval IDs:

```python
class ApprovalBroker:
    def request(...)
    def resolve(...)
```

- Add HTTP endpoints:
  - `GET /api/runs`
  - `POST /api/runs`
  - `GET /api/runs/{id}`
  - `GET /api/runs/{id}/events` using SSE
  - `POST /api/runs/{id}/cancel`
  - `POST /api/runs/{id}/approve`
  - `POST /api/runs/{id}/fork`
  - `GET /api/runs/{id}/artifacts/{path}`
- Support event-stream reconnect through `Last-Event-ID` and/or
  `?after_seq=123`.
- Derive frontend objects from events and artifacts:
  `Run`, `Turn`, `ModelCall`, `ToolCall`, `Command`, `Patch`,
  `WorkspaceDelta`, `ContextBuild`, `Approval`, `Artifact`, and `EvalResult`.
- Keep the first server zero-database. Read `events.jsonl`, `metrics.json`,
  `final.md`, `final.diff`, and artifacts. Add SQLite only as an index/cache
  later.

Acceptance criteria:

- CLI, SDK, replay, and server use the same canonical event stream.
- A client can reconnect and reconstruct run state from durable events.
- Fork and approval endpoints operate through explicit runtime primitives.
- UI state is derived, not a second source of truth.
- True live steering and post-crash continuation are deferred until there is a
  real thread/session protocol.

Tests:

- SSE streams events for a fake-provider run.
- SSE reconnect with `after_seq` or `Last-Event-ID` replays missed durable
  events before streaming live events.
- `GET /api/runs/{id}` reconstructs a completed run from disk.
- Cancel endpoint stops an active run.
- Approval endpoint resolves a brokered pending approval.
- Fork endpoint starts from a selected event/run boundary.

## 12. Phase 7: Eval Comparison Loop

Branch: `ta-eval-compare`

Purpose: make harness changes measurable.

Changes:

- Add `agentd/config.py` with a `RunConfig` loader before variant comparison.
  The config should cover:
  - provider
  - model spec
  - profile
  - visible tools
  - context config
  - policy config
  - sandbox mode
  - workspace mode
  - hooks/extensions
  - budgets
- Add:

```bash
agentctl eval compare suites/editing \
  --variant baseline=configs/baseline.toml \
  --variant contextfs2=configs/contextfs2.toml
```

- Generate per-variant and delta reports for:
  - solve rate
  - validation pass rate
  - tokens in/out
  - tool calls
  - failed tool calls
  - repeated tool calls
  - time to first edit
  - time to verification
  - mutations without diff inspection
  - mutations without verification
  - context compactions
  - ContextFS recovery reads
  - policy denials
  - sandbox blocks
  - finish-gate interventions
  - output truncation and artifact counts
- Map failures to harness categories:
  context missing, observation missing, policy wrong, sandbox too tight,
  execution failed, provider malformed, loop not detected, verifier absent, or
  finish gate weak.
- Include reproducibility metadata for every variant:
  - git sha
  - branch
  - config hash
  - model id
  - provider
  - profile name
  - visible tool names
  - sandbox mode
  - context config

Acceptance criteria:

- Existing eval suites and thresholds remain compatible.
- Variant comparison can run fake providers deterministically.
- Reports make it obvious whether a harness branch improved or regressed the
  target behavior.
- Comparison reports are interpretable from config and git metadata alone.

Tests:

- Two fake variants produce a comparison report.
- A run with shell mutation but no diff inspection reports
  `mutation_without_diff`.
- A sandbox-denied command increments sandbox metrics and category.
- Threshold failures include variant names.
- Config hash and selected model/profile/tool metadata appear in the report.

## 13. Side Stack: First Enforced Sandbox Backend

Branch: `ta-container-sandbox`

Base: `ta-sandbox-contract`

Purpose: add one real execution boundary behind the sandbox contract without
blocking the rest of the main harness stack.

Preferred first backend:

- Docker or Podman container mode, because it is practical across many
  developer machines and avoids writing native policy first.

Container behavior:

- Fail at run setup if `sandbox_mode=container` is requested and Docker/Podman
  is unavailable. Do not defer this into a random shell failure.
- Run the container as the current UID/GID where possible so generated files do
  not become root-owned.
- Mount the effective workspace read-write at `/workspace` and run commands
  with `/workspace` as the working directory.
- Set an isolated home, for example `/home/tinyagent`.
- Do not mount host `~/.ssh`, shell history, global git config, credentials,
  cloud config directories, package manager tokens, or parent directories.
- Handle Git safe-directory behavior by setting temporary config inside the
  isolated home, for example `git config --global --add safe.directory
  /workspace`.
- Define network modes explicitly:
  - `network=deny -> docker/podman --network none`
  - `network=ask -> policy approval path`
  - `network=allow -> normal network`
- Preserve current timeout, output cap, process cancellation, and artifact
  behavior.
- Return structured sandbox failures when a command requests denied access.
- State clearly that the container backend applies primarily to process
  execution, especially `shell`. In-process tools such as `apply_patch`,
  `read_file`, and `search_repo` still run in the host Python process and must
  remain protected by path policy.

Later native backends:

- macOS `sandbox-exec`/Seatbelt profile generation.
- Linux Landlock/seccomp or bubblewrap.
- Windows through WSL2 first; native Windows only when there is a concrete
  backend with acceptable developer-tool support.

Acceptance criteria:

- `sandbox_mode=container` enforces workspace-scoped writes and isolated home.
- Network commands fail with `sandbox_blocked + capability=network` unless
  explicitly allowed.
- Common local test/build commands still work when they do not require external
  access.
- Sandbox constraints are visible in shell result summaries and metadata.
- Files created in the workspace are owned by the current user where the runtime
  supports UID/GID mapping.

Tests:

- Command can write inside `/workspace`.
- Command cannot write outside the mounted workspace.
- Command cannot read a fixture secret outside workspace.
- `curl https://example.com` fails as `sandbox_blocked` with
  `capability=network` by default.
- Container runtime missing yields a clear setup failure, not an unknown tool
  error.
- Git commands work inside a mounted git repo after safe-directory setup.

## 14. Later Work

Do not start these before the core stack above is stable:

- project-local skills/prompts/extensions under `.tinyagent/`
- diagnostics provider for likely project checks
- one scoped `delegate` tool that forks a child run and returns a summary
- MCP adapter after dynamic tool docs and sandboxing are in place
- native macOS/Linux sandbox backends after the container backend proves the
  sandbox contract
- SQLite index/cache for large run stores
- richer web UI panes and dashboards

## 15. Non-Goals

- No baked-in plan mode in the kernel.
- No todo ontology or workflow graph runtime.
- No multi-agent manager as core architecture.
- No memory database before session files and ContextFS are strong.
- No MCP before sandboxing and dynamic tool discovery.
- No provider hacks in the kernel.
- No prompt-only safety story for filesystem, network, or secret boundaries.

## 16. Cross-Branch Constraints

- Keep kernel changes small and mechanically reviewable.
- Preserve existing CLI, replay, inspect, SDK, and eval behavior unless a branch
  explicitly extends them.
- Large payloads belong in artifacts; events and state carry summaries, refs,
  and small metadata.
- Every new runtime guarantee needs an event, an observation or metric, and at
  least one regression test.
- Work with existing uncommitted docs; do not sweep unrelated generated exports
  or local artifacts into implementation branches.
- Treat unsupported sandbox/provider/edit-tool behavior as explicit failure,
  not silent fallback.
- The delta observer must ignore tinyagent-owned artifacts and ContextFS writes.
- ContextFS files intended for model recovery must be readable through a safe
  first-party mechanism.
- Server v1 supports reconnect and replay; true run continuation and live
  steering are later unless explicitly implemented.

## 17. First Five PRs

1. Expose `read_file` and `search_repo` in the default profile and make
   structured inspection count as evidence.
2. Add `WorkspaceDeltaObserver` and make finish gates mutation-based.
3. Split worktree isolation from real sandbox modes and render sandbox
   constraints clearly.
4. Add `ModelSpec`-driven edit tool selection.
5. Upgrade ContextFS with safe recovery reads, then build the runtime server and
   eval comparison on top.

The enforced container backend is the first side-stack PR after
`ta-sandbox-contract`, not a blocker for the main stack.
