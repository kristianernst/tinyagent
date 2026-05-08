# Stage 6a — Skill Draft Learning Loop

## Problem

Tinyagent records rich traces but does not yet turn successful patterns into reusable skills. Hermes shows the value of skill creation and improvement, but tinyagent should keep this reviewable.

## Target design

Add a post-run command:

```text
tinyagent skills draft-from-run <run_id>
```

or:

```text
tinyagent learn skill-draft <run_path>
```

It creates:

```text
.tinyagent/skill-drafts/<draft_id>/SKILL.md
.tinyagent/skill-drafts/<draft_id>/source-run.json
.tinyagent/skill-drafts/<draft_id>/eval-plan.md
```

## Draft generation inputs

Use:

- final output;
- events;
- tool transcript;
- changed files/diff;
- successful verification commands;
- ContextFS observations;
- project instructions.

Do not include hidden model request artifacts unless local debug mode explicitly permits.

## Draft structure

`SKILL.md` should include:

```markdown
---
name: proposed-skill-name
description: When to use this skill.
tags: [coding, debug]
---

# Skill

## When to use

## Procedure

## Commands

## Verification

## Failure modes

## Source trace
```

## Review flow

Commands:

```text
tinyagent skills list-drafts
tinyagent skills show-draft <id>
tinyagent skills install-draft <id>
tinyagent skills reject-draft <id>
```

## Tests

- Draft generation from a successful edit run.
- Draft does not include hidden artifacts/secrets.
- Install copies draft to configured skill source.
- Reject archives/removes draft.

## Exit criteria

- Successful traces can produce skill drafts.
- Drafts are not auto-installed.
- Human review is required.

## Why this matters

This gives tinyagent a learning path while preserving the file-backed, explicit philosophy.
