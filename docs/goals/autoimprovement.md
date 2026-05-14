# Tinyagent Autoimprovement Goal

## Goal

Make tinyagent installable, easy to experiment with, and measurable enough that changes to prompts, context, tools, profiles, providers, and skills can be evaluated instead of vibe-checked.

The target is an autoresearch and evaluation loop:

1. collect representative tasks;
2. run tinyagent across a controlled variant matrix;
3. mine traces for capability, context, efficiency, safety, and failure patterns;
4. generate reports with concrete regressions and improvement candidates;
5. produce reviewable prompt, profile, tool-description, or skill changes;
6. rerun the same suites before anything is accepted.

Core code self-modification should remain out of scope until the eval and rollback story is strong. The first learning target should be reviewable skills, prompts, profile settings, tool descriptions, and context policies.

## Web Research Summary

The useful pattern across current agent-eval systems is trace first, dataset second, optimization third.

- OpenAI's agent-eval guidance separates trace grading for debugging from datasets and eval runs for repeatable benchmarking. That matches tinyagent's current event-ledger design: use per-run traces to understand failures, then promote stable traces into repeatable suites. Sources: [OpenAI agent workflows](https://developers.openai.com/api/docs/guides/agent-evals), [OpenAI trace grading](https://developers.openai.com/api/docs/guides/trace-grading).
- Inspect AI treats evals as tasks with logs, agents, sandboxes, limits, eval sets, and data-frame extraction. Its Agent Bridge can wrap third-party or CLI agents inside sandboxes, including Codex-style CLI agents. This suggests tinyagent should keep its local runner, but later expose an Inspect bridge for external benchmark compatibility. Sources: [Inspect](https://inspect.aisi.org.uk/), [Inspect Agent Bridge](https://inspect.aisi.org.uk/agent-bridge.html).
- LangChain AgentEvals and MLflow both emphasize trajectory evaluation, not just final answer scoring. Deterministic tool-call trajectory checks are useful when the expected path is known; LLM or human judges are useful only where deterministic validation is not enough. Sources: [LangChain Agent Evals](https://docs.langchain.com/oss/python/langchain/test/evals), [MLflow trace evaluation](https://mlflow.org/docs/latest/genai/eval-monitor/running-evaluation/traces/), [MLflow tool-call judges](https://mlflow.org/docs/latest/genai/eval-monitor/scorers/llm-judge/tool-call/).
- Coding-agent benchmarks point toward executable tasks with isolated workspaces and verifiers. SWE-bench Verified is useful for real GitHub issue style work, but static datasets have contamination and scope limits. Terminal-Bench is closer to terminal-native, long-horizon operation because every task has an instruction, environment, and tests. Sources: [SWE-bench Verified](https://openai.com/index/introducing-swe-bench-verified/), [Terminal-Bench 2.0](https://arxiv.org/abs/2601.11868), [Epoch Terminal-Bench](https://epoch.ai/benchmarks/terminal-bench).
- Self-improvement work supports the direction, with guardrails. Reflexion turns task feedback into textual lessons stored outside model weights. DSPy's MIPROv2 and TextGrad show prompt and component optimization against metrics, but both rely on a real objective function. Tinyagent should adopt the structure, not the hype: candidates must be generated out of tree, scored on held-out tasks, and human-reviewed before install. Sources: [Reflexion](https://arxiv.org/abs/2303.11366), [DSPy MIPROv2](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/api/optimizers/MIPROv2.md), [TextGrad](https://arxiv.org/abs/2406.07496), [Self-Refine](https://arxiv.org/abs/2303.17651).

## Current Tinyagent Assessment

Tinyagent already has more of the right substrate than a fresh project:

- Install surface: `pyproject.toml` exposes `tinyagent = "tinyagent.cli:main"` and packages `tinyagent/`.
- Product surface: `tinyagent init`, `run`, `serve`, `doctor`, `workspaces`, `conversations`, `replay`, `inspect`, `eval`, `skills`, `memory`, and `evolve` exist.
- Experiment surface: `tinyagent/evals/runner.py` supports eval cases, isolated workspaces, validation commands, result JSONL, markdown reports, variant comparison, and threshold checks.
- Metrics surface: `tinyagent/evals/metrics.py` mines event traces for token estimates, visible tools, tool errors, policy denials, sandbox blocks, compactions, repeated commands, first-tool/edit timing, context reads, skill usage, MCP usage, invariants, and harness findings.
- Trace contract: `tinyagent/evals/invariants.py` checks event ordering, turns, steps, model calls, tool calls, workspace deltas, approvals, artifacts, and finalization.
- Learning surface: `tinyagent skills draft-from-run`, `skills eval-draft`, and `evolve skill/prompt/report/accept` exist and are intentionally reviewable/out-of-tree.
- Provider surface: OpenAI-compatible Chat Completions works through `TINYAGENT_MODEL_BASE_URL`, `TINYAGENT_MODEL_API_KEY`, and `TINYAGENT_MODEL_NAME`; real protocol tests are gated behind `TINYAGENT_RUN_INTEGRATION=1`.

I fixed one immediate experimentability blocker while preparing this plan: the README-visible fake eval smoke path now passes. Before the fix, `tinyagent eval evals/tiny --provider fake` passed only 1 of 3 cases because the fake provider read files but did not edit. The fake provider now has deterministic task fixtures for the bundled tiny eval suite, and `tests/test_cli.py` asserts that the smoke suite returns 3/3.

Current local evidence:

```bash
uv run tinyagent doctor --workspace . --provider fake
uv run tinyagent eval evals/tiny --provider fake --output-dir /private/tmp/tinyagent-autoimprovement-eval-fixed2
uv run pytest tests/test_cli.py::test_tinyagent_eval_fake_smoke_suite_passes tests/test_cli.py::test_tinyagent_run_fake_and_replay tests/test_eval_runner.py::test_eval_suite_runs_cases_and_writes_report
```

Observed result after the fix: doctor is OK, fake eval solves 3/3 with no tool errors, and the focused tests pass.

## Capability Assessment

Tinyagent can support the autoimprovement loop, but only within a controlled boundary.

What tinyagent can do now:

- run deterministic smoke evals without a model key;
- run local task suites with executable validation;
- compare supported variants of provider, model, profile, visible tools, workspace mode, approval mode, and sandbox mode;
- emit enough trace data to analyze context size, tool schema size, tool trajectory, policy blocks, verification behavior, and final diffs;
- generate reviewable skill drafts and out-of-tree prompt/skill experiments.

What tinyagent cannot credibly claim yet:

- general coding-agent readiness across real tasks;
- autonomous self-improvement of core code;
- performance numbers that mean anything beyond the tiny local suite;
- strong sandbox isolation on machines without a usable Docker or Podman backend and image;
- robust local-model support unless the chosen endpoint actually emits OpenAI-compatible tool calls.

What I can do as Codex in this repo:

- research current methods and turn them into small Graphite-stacked changes;
- write eval cases, reports, adapters, and trace miners;
- run local tests and fake-provider smoke suites;
- inspect real trace artifacts and fix broken tool/provider paths;
- use web research and repo evidence to propose candidate changes.

What I should not do without explicit review gates:

- let tinyagent rewrite or install its own core code automatically;
- accept prompt/skill/profile changes based on training-suite gains alone;
- claim benchmark progress without held-out tasks and trace artifacts;
- run networked or costly model experiments without explicit environment and budget controls.

## Target Architecture

Keep this as a thin benchmark/research layer over existing primitives, not a new workflow engine.

### 1. Suite Registry

Add a first-class local catalog for suites:

```text
evals/
  tiny/                  # always-green harness smoke
  coding/                # small repo edits with pytest/ruff validation
  context/               # retrieval and context-budget tasks
  protocol/              # tool-call protocol conformance tasks
  regressions/           # failures promoted from real runs
  external/              # imported/adapted benchmark shards
```

Each case should stay simple:

```json
{
  "id": "case-id",
  "task": "human task text",
  "validation_command": "pytest",
  "timeout_seconds": 120,
  "setup_git": true,
  "tags": ["coding", "context"],
  "difficulty": "smoke|small|medium",
  "expected_mechanisms": ["inspect_before_edit", "diff_after_edit", "verification_after_edit"]
}
```

### 2. Baseline Runner

Add a command or script that creates reproducible baselines:

```bash
tinyagent bench run evals/coding \
  --variant baseline=configs/evals/baseline.toml \
  --variant small-tools=configs/evals/small-tools.toml \
  --output-dir .tinyagent/benchmarks/<suite>-<timestamp>
```

This can initially wrap `tinyagent eval compare`; the important part is stable output paths, config capture, git state capture, and a single report index.

### 3. Trace Miner

Extend existing metrics into a report that answers:

- what context was shown before each model call;
- which files and artifacts the agent inspected;
- tool-call sequence and redundancy;
- time to first useful edit;
- verification and diff discipline;
- policy, sandbox, provider, parser, and tool failures;
- cost proxy: static prompt tokens, tool schema tokens, context tokens, model calls, tool calls;
- final diff quality and validation result.

The trace miner should read existing `events.jsonl`, `context-report-*.json`, `context-*.md`, `model-request-logical-*.json`, `final.diff`, and validation outputs. It should not require external services.

### 4. Autoresearch Reporter

Generate `report.md` plus `report.json` for every benchmark run:

- headline score and regression summary;
- per-case failures with links to run artifacts;
- context waste and missing-context findings;
- tool inefficiency and repeated-command findings;
- provider/tool protocol failures;
- recommended next experiments;
- candidate changes that are allowed to be generated.

The report should be good enough to send to another model or reviewer without opening the whole repo.

### 5. Candidate Generator

Keep candidates out of tree:

```text
.tinyagent/evolution/experiments/<id>/
  experiment.json
  baseline/
  candidates/candidate-1/
  reports/report.md
  accepted/
```

Allowed first targets:

- skill drafts from successful traces;
- prompt/profile text candidates;
- tool descriptions and schema descriptions;
- context-source ranking and inclusion policy;
- eval case additions from observed failures.

Disallowed initially:

- automatic core code patches;
- automatic install of candidates;
- using the same public suite as both optimizer and proof;
- hidden memory updates.

## Benchmark Ladder

Use a ladder so tinyagent can improve without pretending a tiny suite is a full benchmark.

| Level | Purpose | Gate |
| --- | --- | --- |
| L0 fake smoke | Install and harness health | `evals/tiny` passes with fake provider |
| L1 protocol smoke | Real endpoint can call tools correctly | gated integration tests pass |
| L2 local coding small | Can edit, test, and report in small repos | >= target solve rate, zero trace invariant failures |
| L3 context efficiency | Can find relevant context without bloat | lower context/tool tokens at equal solve rate |
| L4 regression bank | Real failures stay fixed | no regression on promoted failure cases |
| L5 external shard | Compare to broader ecosystems | Inspect/Terminal-Bench/SWE-bench adapter runs a small shard |
| L6 nightly matrix | Track drift across providers/profiles | report trend and fail thresholds |

## Action Plan

### Phase 0: Keep The Harness Green

Exit criteria:

- `uv run tinyagent doctor --workspace . --provider fake` is OK.
- `uv run tinyagent eval evals/tiny --provider fake` returns 0.
- README install/try commands are true.
- focused CLI/eval tests cover the smoke path.

Status: started in this branch. The fake smoke blocker is fixed.

### Phase 1: Make Install And First Experiment Boring

Work:

- add `docs/INSTALL.md` or tighten README around `uv tool install -e .`, local editable install, and provider env vars;
- add `tinyagent doctor --provider openai-compatible` examples for local and hosted endpoints;
- add one command that prints the current experiment matrix and where outputs land;
- make package build part of verification.

Exit criteria:

- a fresh clone can run fake smoke in under a minute;
- a configured OpenAI-compatible endpoint can run the protocol smoke;
- `uv build` succeeds.

### Phase 2: Add A Real Local Task Suite

Work:

- create `evals/coding-small` with 10 to 20 small tasks across bug fix, refactor, docs/code sync, test failure, config edit, and tool-error recovery;
- add tags and difficulty metadata to case loading without breaking existing cases;
- add threshold files for smoke, local, and integration modes;
- include at least one task that requires context search and one that penalizes unnecessary context bloat.

Exit criteria:

- deterministic validation exists for every case;
- result rows include tags/difficulty;
- reports can summarize by tag.

### Phase 3: Turn Trace Mining Into A Diagnosis Report

Work:

- add `tinyagent eval analyze <eval-output>` or `tinyagent bench report <output-dir>`;
- include per-case links to artifacts;
- summarize context token estimate, tool schema tokens, model calls, tool calls, repeated commands, policy blocks, verification discipline, and diff discipline;
- add "likely blocker" categories: provider_no_tool_calls, policy_blocked_verification, context_missing, context_bloat, repeated_no_progress, validation_failed_after_success_claim, final_diff_missing.

Exit criteria:

- a failed eval produces a report that tells us what to fix next;
- no manual JSONL spelunking is needed for common failures.

### Phase 4: Add Baseline Variant Matrix

Work:

- create checked-in configs under `configs/evals/`;
- compare `tiny-coder`, `tiny-pi`, visible tool subsets, context policies, sandbox modes, and provider/model names;
- support repeated runs for non-deterministic models;
- keep eval costs explicit in report metadata.

Exit criteria:

- `tinyagent eval compare` can produce stable baseline vs candidate reports;
- reports include config hash, git SHA, dirty state, and suite hash;
- threshold checks can block regressions.

### Phase 5: Context Efficiency Loop

Work:

- persist model-facing context summaries per model call in the report;
- add context recall checks for tasks where a specific file or instruction must be included;
- add context waste checks for oversized static prompts, redundant tool schemas, repeated context reads, and irrelevant artifacts;
- compare alternate context policies against solve rate and token estimates.

Exit criteria:

- changes to context policy must show equal or better solve rate with lower or justified context cost;
- context failures become concrete report findings.

### Phase 6: Reviewable Improvement Candidates

Work:

- connect failed/successful traces to candidate generation;
- generate skill drafts only from successful, validated traces;
- generate prompt/profile/tool-description candidates from aggregate report findings;
- run baseline-vs-candidate on training and held-out suites;
- require human accept before install.

Exit criteria:

- every accepted candidate has source traces, diff, eval comparison, and rollback path;
- no candidate is accepted only because it improved the training suite.

### Phase 7: External Benchmark Bridges

Work:

- add an adapter layer for a small Inspect task bridge;
- evaluate whether Terminal-Bench can run tinyagent as the agent binary inside its harness;
- defer SWE-bench until install, sandbox, and long-run controls are stable;
- treat external scores as compatibility and stress evidence, not the only product metric.

Exit criteria:

- tinyagent can run at least one external benchmark shard or bridge without special manual glue;
- external run reports link back to tinyagent traces.

### Phase 8: Automation Cadence

Work:

- add local scripts for quick, standard, and expensive eval runs;
- keep live model/protocol tests opt-in;
- optionally add a scheduled local/CI job for fake smoke and small local suites;
- generate weekly benchmark reports from stored outputs.

Exit criteria:

- cheap checks are always runnable;
- expensive checks are gated by env vars and budget notes;
- historical reports are comparable.

## Graphite Stack Shape

Use small stacked branches:

1. `ta-autoimprove-goal-doc`: this plan plus fake smoke fix.
2. `ta-install-experiment-smoke`: install docs, build check, doctor examples.
3. `ta-eval-case-metadata`: tags/difficulty/expected mechanisms in eval cases.
4. `ta-coding-small-suite`: first real local benchmark suite.
5. `ta-eval-report-analyze`: report command over existing eval outputs.
6. `ta-context-efficiency-metrics`: context recall/waste metrics.
7. `ta-evolution-candidates`: report-driven candidate generation and held-out eval comparison.
8. `ta-external-benchmark-bridge`: Inspect or Terminal-Bench bridge spike.

Each branch should have focused tests and should not mix benchmark data churn with core runtime changes.

## Immediate Blocker List

- Fake smoke path was broken; fixed in this branch.
- The fake smoke still reports `verification_after_edit_missing` for `patch-format` because that fixture only has a harness validation script, not an in-agent test command. This is acceptable for L0 but should be removed from real suites.
- `python3 -m pytest` is not currently allowed by default shell policy, while `pytest`, `python -m pytest`, and `uv run pytest` are. Either document this or expand the allowlist deliberately.
- `eval compare` validates only a narrow set of profiles/config fields. That is good for safety, but the benchmark layer needs explicit supported variants rather than arbitrary config mutation.
- The sandbox backend is opportunistic. Container mode depends on Docker or Podman being installed and the image already available because `--pull never` is used.
- Real model capability depends on OpenAI-compatible tool-call behavior. Chat-only local endpoints can appear healthy but fail to mutate workspaces.
- Repo-wide `uv run ruff check .` is currently red from existing lint debt outside this change. The edited Python files pass targeted ruff checks.
- The eval corpus is too small to make performance claims.
- There is no report index across benchmark runs yet.
- There is no held-out split for optimization candidates yet.

## Next Concrete Step

After this plan lands, implement Phase 1 and Phase 2 together only far enough to make a credible first benchmark loop:

```bash
uv run tinyagent doctor --workspace . --provider fake
uv run tinyagent eval evals/tiny --provider fake
uv run tinyagent eval evals/coding-small --provider openai-compatible --stream text
uv run tinyagent eval compare evals/coding-small \
  --variant baseline=configs/evals/baseline.toml \
  --variant small-tools=configs/evals/small-tools.toml
```

Do not optimize prompts or skills until the small real suite, held-out split, and trace report exist.
