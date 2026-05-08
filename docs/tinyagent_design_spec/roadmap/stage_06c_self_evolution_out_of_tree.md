# Stage 6c — Self-Evolution Out of Tree

## Problem

Self-improving agents are useful but risky. Optimizing prompts, tool descriptions, policies, or code inside the main run loop can make behavior opaque and hard to roll back.

## Target design

Keep self-evolution as an out-of-tree optimization pipeline.

```text
.tinyagent/evolution/
  experiments/
  candidates/
  reports/
  accepted/
```

Targets, in risk order:

1. Skill drafts.
2. Tool descriptions.
3. Prompt templates.
4. Profile config.
5. Core code — not supported initially.

## Workflow

1. Select target.
2. Build eval suite.
3. Generate candidate.
4. Run eval comparison.
5. Produce report.
6. Human accepts/rejects.
7. Accepted candidate becomes normal resource.

## Commands

```text
tinyagent evolve skill <skill-id> --suite evals/...
tinyagent evolve prompt tiny-pi --suite evals/...
tinyagent evolve report <experiment-id>
tinyagent evolve accept <candidate-id>
```

## Safeguards

- No candidate auto-installs.
- Every candidate has source diff and eval report.
- Rollback path recorded.
- Core code evolution disabled unless explicitly experimental.

## Exit criteria

- Skill/prompt evolution can run as an external workflow.
- Results are ordinary files.
- Accepted outputs integrate through ResourceLoader.

## Why this matters

This borrows Hermes’s learning ambition while respecting tinyagent’s explicit, reviewable design.
