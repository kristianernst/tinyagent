# Stage 6 — Optional Memory and Self-Improvement

## Goal

Add a Hermes-inspired self-improvement path without turning tinyagent into an opaque memory system.

## Why this is necessary

Long-lived agents improve when they can reuse successful procedures. But persistent memory and self-modification can quickly violate tinyagent’s lean, explicit design. Stage 6 therefore focuses on reviewable skill drafts, not hidden memory.

## Substages

1. `stage_06a_skill_draft_learning_loop.md`
2. `stage_06b_memory_as_files.md`
3. `stage_06c_self_evolution_out_of_tree.md`

## Primary changes

- Mine successful traces for reusable procedures.
- Generate `SKILL.md` drafts in a draft directory.
- Run evals comparing baseline vs draft-enabled behavior.
- Require human review before installing skills.
- Keep persistent memory as files, not hidden core state.
- Keep optimization pipelines out of the run loop.

## Non-goals

- No autonomous core code modification.
- No hidden user model in core.
- No automatic skill installation from one trace.
- No default memory in `tiny-pi`.

## Exit criteria

- Skill drafts can be generated from traces.
- Drafts are human-readable and reviewable.
- Drafts can be eval-tested before installation.
- Installed skills are ordinary skill resources.

## Why this comes late

Self-improvement depends on stable traces, skills, evals, and resource loading. Without those, learning becomes opaque and unsafe.
