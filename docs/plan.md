# tinyagent Pro Update Implementation Plan

Status: planning draft
Source: docs/pro-update.md
Workflow: Graphite stacked branches, each branch reviewable on its own

## 1. Summary

The pro update argues that tinyagent already has the right visible shape: a small
kernel, a profile-driven run loop, and a default two-tool coding surface
(`shell` and `apply_patch`). The implementation work should therefore avoid a
rewrite or a larger tool catalog. The goal is to make the harness more
perceptive behind the scenes:

- canonical transcript invariants instead of ad hoc history
- typed observations extracted from raw tool results
- dynamic context planning instead of only static layer packing
- pure progress guardrails for no-progress loops
- explicit execution envelopes for safer autonomy
- provider capability modeling to keep provider quirks out of the kernel
- a minimal extension host over the existing hook shape
- eval analysis that turns traces into harness-quality feedback

The stack should be built bottom-up. Each branch introduces one durable
primitive and leaves the model-facing behavior as stable as possible.

## 2. Graphite Stack Shape

Start from current `main` and keep each milestone as a Graphite branch stacked
on the previous one.

```bash
gt checkout main
gt create ta-pro-plan-docs -a -m "Add pro update implementation plan"
gt create ta-transcript-core --onto ta-pro-plan-docs -m "Add canonical transcript substrate"
gt create ta-observations --onto ta-transcript-core -m "Extract typed observations from tool results"
gt create ta-context-plan --onto ta-observations -m "Add dynamic context planning"
gt create ta-progress-guard --onto ta-context-plan -m "Add progress guardrails"
gt create ta-execution-envelope --onto ta-progress-guard -m "Formalize execution envelopes"
gt create ta-model-capabilities --onto ta-execution-envelope -m "Add model provider capabilities"
gt create ta-extension-host --onto ta-model-capabilities -m "Add minimal extension host"
gt create ta-eval-analysis --onto ta-extension-host -m "Add harness eval analysis"
```

Validate and submit the full stack only after the whole stack is green:

```bash
PYTHONPATH=. pytest
gt submit --stack --dry-run
gt submit --stack --confirm
```

If a branch needs revision after review:

```bash
gt checkout <branch>
git status
git diff
gt modify -a -m "<updated message>"
gt restack
PYTHONPATH=. pytest
gt submit --stack --dry-run
```

## 3. Milestone 0: Planning Branch

Branch: `ta-pro-plan-docs`

Purpose: capture the implementation roadmap derived from `docs/pro-update.md`
before making runtime changes.

Changes:

- Add this plan in `docs/plan.md`.
- Include `docs/pro-update.md` in the branch if it is still untracked when the
  branch is created, so the implementation rationale travels with the plan.
- Do not include unrelated untracked docs unless explicitly requested.

Acceptance criteria:

- Documentation-only diff.
- Plan clearly names every Graphite branch, dependency, and acceptance gate.
- No runtime code, tests, lockfiles, or generated source exports are changed.

Verification:

```bash
git diff -- docs/plan.md docs/pro-update.md
```

## 4. Milestone 1: Transcript And Evidence Substrate

### Branch: `ta-transcript-core`

Purpose: add a canonical transcript substrate that makes model responses, tool
calls, tool results, compactions, and synthetic harness messages replayable with
clear invariants.

Implementation details:

- Add a new transcript module, likely `agentd/transcript.py`, with immutable or
  append-only record types for:
  - model calls and model responses
  - tool calls and tool results
  - synthetic tool results for blocked calls
  - finish-gate injected messages
  - compaction records
  - rollback or branch boundaries, even if rollback is only structural in v1
- Store the transcript on `RunState` while keeping `RunState.tool_steps` as the
  compatibility path for existing context, finish-gate, replay, and tests.
- Route kernel recording through transcript helpers at the existing boundaries:
  model response completed, tool call requested, policy-hidden or unknown tool
  result, tool execution result, finish blocked, and compaction completed.
- Enforce minimal invariants:
  - every recorded tool result has a matching call ID
  - every dispatched model tool call eventually receives a tool result
  - hidden and unknown tools are recorded as results, not dropped
  - large payloads stay artifact-backed instead of embedded into transcript data
- Preserve the existing event log and artifact format unless a later eval branch
  deliberately extends them.

Acceptance criteria:

- Existing public behavior remains unchanged.
- Replay and context reports still work with the compatibility `tool_steps`
  view.
- Transcript data can be serialized without including large raw artifacts.
- Kernel code has one obvious path for recording tool-call/result pairs.

Tests:

- Model response with one tool call records one transcript call and one result.
- Unknown tool and hidden tool calls record failed results with call IDs.
- Policy denial records a synthetic failed tool result.
- Finish-gate blocked response records an injected transcript item.
- Existing replay, kernel, and context tests still pass.

### Branch: `ta-observations`

Purpose: add a typed observation layer so the harness can understand what raw
tool output means without exposing more structure to the model.

Implementation details:

- Add an `Observation` dataclass with fields along these lines:
  - `kind`: a stable string or literal such as `command_failed`, `test_run`,
    `test_failure`, `file_changed`, `diff_seen`, `verification`, `policy_block`,
    `patch_applied`, `search_result`, `dependency_error`, or `sandbox_block`
  - `subject`: command, path, test target, policy permission, or affected file
  - `summary`: short human-readable evidence summary
  - `confidence`: default `1.0`
  - `refs`: artifact paths, call IDs, or file paths
  - `data`: small structured metadata only
- Add an observer/extractor module, likely `agentd/observations.py`.
- Extract observations from existing `ToolResult` metadata instead of parsing
  arbitrary command output first. Use command text, exit code, failure kind,
  patch metadata paths, read hints, and context artifacts as primary inputs.
- Teach shell extraction to classify:
  - `pytest`, `unittest`, `ruff`, `mypy`, `npm test`, `cargo test`, and `go test`
    as verification/test commands
  - nonzero verification commands as test failures or command failures
  - `git diff`, `git show`, and relevant file inspections as evidence
  - `rg` commands as search observations with command and artifact refs
- Teach patch extraction to classify changed paths from `metadata["paths"]` or
  `data["paths"]`.
- Store observations on `RunState` and emit an `observation.recorded` event with
  small data only.

Acceptance criteria:

- Observations are deterministic and cheap.
- Finish gates and future context planning can consume observations without
  reparsing tool output.
- Observation extraction does not break existing tool result schemas.

Tests:

- Successful and failing pytest commands produce verification/test observations.
- Failed non-test shell command produces `command_failed`.
- `git diff` or `git show` produces `diff_seen`.
- Patch results produce one or more `file_changed` observations.
- Policy-denied tool calls produce `policy_block`.
- Observation events omit large output payloads.

## 5. Milestone 2: Context Intelligence

### Branch: `ta-context-plan`

Purpose: replace purely static context packing with a small planning layer that
selects evidence based on the next likely task mode.

Implementation details:

- Add a `ContextPlan` type, likely in `agentd/context/types.py`, with:
  - selected mode: `explore`, `edit`, `debug`, `verify`, `summarize`, or `finish`
  - pinned item IDs or observation kinds
  - recent-tail budget
  - included observation kinds
  - omitted artifact refs
  - a short reason string for reports
- Add a profile method or compatibility hook, for example
  `plan_next_context(state) -> ContextPlan`.
- Implement deterministic v1 planning in `ApexCoderProfile`:
  - `explore`: no edits yet, prioritize task, project instructions, contextfs,
    recent search/file reads
  - `edit`: after relevant inspection but before edits, keep changed target
    files and most recent search evidence
  - `debug`: after failing tests or command failures, keep failing command,
    failure artifact, latest edits, and relevant changed files
  - `verify`: after edits without passing verification, keep latest patch,
    changed files, and candidate verification commands
  - `finish`: after passing verification or explicit limitation, keep diff,
    verification evidence, policy/sandbox limitations, and finish-gate feedback
  - `summarize`: when compaction is near, prioritize durable known facts,
    unresolved issues, changed files, and artifact refs
- Teach `ContextBuilder` to consume the plan while preserving current layers:
  system prompt, environment, project instructions, task, contextfs index,
  finish gate, checkpoint, and recent tools.
- Add plan metadata to context reports: selected mode, reason, included
  observation kinds, and exclusions.

Acceptance criteria:

- Existing context output remains recognizable.
- Failing-test evidence survives context pressure.
- Latest edit, latest diff, latest verification, and latest failure are pinned
  when relevant.
- Context reports explain why important items were included or excluded.

Tests:

- Debug mode keeps failing test output even under a tiny recent-tool budget.
- Verify mode keeps latest patch evidence and asks for verification evidence.
- Finish mode keeps diff and passing verification evidence.
- Static context tests still pass with added plan metadata.

### Branch: `ta-progress-guard`

Purpose: stop obvious no-progress loops with a pure harness-side guard that
inspects transcript and observations.

Implementation details:

- Add a `ProgressGuard` protocol and default implementation.
- Invoke it before tool execution and after result recording.
- Keep it pure: it should return allow/block/guidance decisions and never mutate
  state directly.
- Detect:
  - exact repeated failed shell command
  - same tool plus same args repeatedly failing
  - repeated read-only commands with no new observations
  - repeated patch failures with the same error
  - edit attempts after recent policy/sandbox blocks without changed approach
- When blocking, record a synthetic failed tool result with `failure_kind`
  `progress_blocked` and model-visible guidance that names the repeated pattern.
- Avoid blocking legitimate retry after changed inputs, changed cwd, changed
  command, or newly observed evidence.

Acceptance criteria:

- Guard prevents thrashing without becoming a planner.
- The model receives actionable feedback through normal tool-result channels.
- Existing policy repeated-command behavior remains compatible.

Tests:

- Three identical failed commands trigger a progress block.
- A modified command after a failure is allowed.
- Repeated `sed`/`rg` reads with no new observations trigger guidance.
- Successful new evidence resets the no-progress counter.

## 6. Milestone 3: Safety And Provider Foundation

### Branch: `ta-execution-envelope`

Purpose: make execution boundaries explicit so tinyagent can later swap in
stronger sandbox backends without changing shell semantics.

Implementation details:

- Add execution envelope types for:
  - workspace root and effective cwd
  - sanitized env policy
  - timeout and output caps
  - writable roots
  - network policy metadata
  - process group cancellation behavior
  - sandbox backend name and enforcement status
- Refactor `ShellTool` to build and use an envelope before `subprocess.Popen`.
- Preserve current local execution behavior in the default backend.
- Include envelope metadata in shell `ToolResult.metadata` and relevant events.
- Standardize failure kinds for timeout, cancellation, command failure,
  policy-denied, sandbox-blocked, and unknown execution errors.
- Do not introduce a real OS sandbox in this branch unless it can be done as a
  backend behind the same interface without changing tests or policy semantics.

Acceptance criteria:

- Shell commands still run exactly as before in local mode.
- Timeouts and cancellation still terminate process groups.
- Envelope details are visible in debug events and small result metadata.
- Future sandbox backends have a clear interface.

Tests:

- Timeout behavior unchanged.
- Cancellation behavior unchanged.
- Env remains sanitized.
- Output artifacts and context artifacts still work.
- Envelope metadata appears in command completed/failed events.

### Branch: `ta-model-capabilities`

Purpose: make provider behavior capability-aware so context budgeting and
serialization do not hardcode OpenAI-compatible Chat Completions assumptions.

Implementation details:

- Add `ModelCapabilities` with:
  - context window
  - max output tokens
  - tool support
  - parallel tool support
  - reasoning support
  - image support
  - prompt-cache support
  - tool protocol, initially `chat_completions`
- Add capabilities to `ModelProvider` through an attribute or helper function
  that provides defaults for existing providers.
- Teach `OpenAICompatibleProvider` and `FakeModelProvider` to declare
  capabilities.
- Feed capability values into `ContextConfig` budget decisions where practical.
- Fail clearly if tools are requested for a provider that declares no tool
  support.
- Keep provider-specific payload construction inside providers, not kernel.

Acceptance criteria:

- Existing OpenAI-compatible and fake providers keep working.
- Context budgeting reflects model capability defaults.
- Kernel remains provider-agnostic.
- Unsupported capabilities fail explicitly.

Tests:

- Fake provider exposes deterministic capabilities.
- OpenAI-compatible provider exposes env/config-derived or default
  capabilities.
- Context compact threshold respects context window and output reserve.
- Provider without tool support fails clearly when visible tools are present.

## 7. Milestone 4: Extensibility And Eval Feedback

### Branch: `ta-extension-host`

Purpose: promote the current hook ABI into a small extension host so users can
customize behavior without modifying the kernel.

Implementation details:

- Add `Extension` and `ExtensionHost` types.
- Preserve compatibility with existing `TinyHook` objects.
- Support explicit local extension loading from a conservative location such as
  `.tinyagent/extensions/*.py` or a config file, with no marketplace behavior.
- Let extensions:
  - register hooks
  - register optional tools
  - inject or patch context
  - block or mutate tool calls through existing hook semantics
  - patch tool results
  - observe compaction and finish decisions
- Keep default loading disabled or explicit if there is any ambiguity around
  executing project-local Python code.
- Document the extension lifecycle and safety model in `extensions/README.md`.

Acceptance criteria:

- Existing direct hook injection still works.
- Extensions are loaded deterministically when explicitly enabled.
- Extension failures follow the current hook error policy.
- Hidden extension tools cannot be called unless visible to the model.

Tests:

- Extension injects a context message.
- Extension blocks a tool call and returns a synthetic result.
- Extension mutates a tool result.
- Extension registers a tool that is only callable when visible.
- Hook error policy is honored.

### Branch: `ta-eval-analysis`

Purpose: convert transcripts and observations into eval metrics that identify
harness quality problems.

Implementation details:

- Extend `agentd/eval_metrics.py` with metrics for:
  - inspected before editing
  - diff inspected after editing
  - verification after editing
  - repeated failed command attempts
  - progress-guard interventions
  - finish-gate interventions
  - policy/sandbox blocks reported
  - context token estimate and recent-tool context share
  - large output artifact count and truncation count
  - missing evidence for final claims
- Keep existing eval task format compatible.
- Add report output that maps failures to likely harness fixes:
  context missing, observation missing, policy wrong, execution failed, provider
  malformed, loop not detected, verifier absent, or finish gate weak.
- Prefer deterministic metrics over LLM-judged evals in this branch.

Acceptance criteria:

- Existing eval runner tests pass.
- Metrics can be computed from old event logs where possible and from new
  transcript/observation data where available.
- Threshold failures are clear enough to guide branch-level fixes.

Tests:

- Synthetic run with edit but no verification fails verification metric.
- Synthetic run with repeated failed command counts retries and guard block.
- Synthetic run with finish-gate intervention counts the intervention.
- Large output/truncation metrics are reported.
- Existing eval thresholds remain backward compatible.

## 8. Cross-Branch Constraints

- Preserve the default model-visible tool surface: `shell` and `apply_patch`.
- Do not move planning, todos, or workflow graphs into the kernel.
- Keep large payloads in artifacts and expose only summaries, refs, and small
  metadata in state/events.
- Maintain compatibility with existing CLI, replay, context report, and eval
  surfaces unless the branch explicitly extends them.
- Keep branch diffs reviewable. If a branch grows too large, split it before
  submitting the stack.
- Use structured types and parsers where available. Avoid broad output parsing
  when existing metadata is enough.
- Unsupported provider, sandbox, or extension behavior should fail clearly
  instead of being hidden behind kernel special cases.

## 9. Verification Plan

Run fast tests after each branch:

```bash
PYTHONPATH=. pytest
```

Run focused checks while developing each subsystem:

```bash
PYTHONPATH=. pytest tests/test_kernel.py
PYTHONPATH=. pytest tests/test_context.py
PYTHONPATH=. pytest tests/test_tools.py
PYTHONPATH=. pytest tests/test_eval_runner.py
PYTHONPATH=. pytest tests/test_update_phases.py
```

Use integration tests only when explicitly validating live providers:

```bash
TINYAGENT_RUN_INTEGRATION=1 PYTHONPATH=. pytest tests/integration/test_openai_compat_real.py
```

Before submitting:

```bash
git status
git diff
PYTHONPATH=. pytest
gt log
gt submit --stack --dry-run
```

## 10. Rollout Notes

The safest review order is the same as the stack order. Transcript and
observations should land before context planning, because context planning needs
durable evidence. Context planning and progress guardrails should land before
execution/provider/extensibility work, because they are the most likely to
surface hidden assumptions in the loop. Eval analysis should land last so it can
measure all prior primitives.

If review feedback forces a redesign, revise the lowest affected branch and
restack upward with Graphite. Do not patch around a lower-level abstraction flaw
in a higher branch.

