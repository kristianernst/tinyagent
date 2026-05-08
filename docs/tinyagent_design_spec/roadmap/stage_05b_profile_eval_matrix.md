# Stage 5b — Profile Eval Matrix

## Problem

The repo needs a way to compare harness philosophies. `tiny-pi` should not be judged by intuition. It should be compared against `tiny-coder` and future profile variants.

## Target design

Add an eval matrix that runs the same cases across profile/config variants.

Profiles to compare initially:

- `tiny-pi`;
- `tiny-coder`;
- optional `tiny-pi-safe` if implemented.

Metrics:

- solve rate;
- validation rate;
- prompt token estimate;
- tool schema token estimate;
- total context token estimate;
- tool calls;
- model calls;
- repeated commands;
- diff-after-edit;
- verification-after-edit;
- finish gate blocks;
- policy denials.

## Implementation

Extend `eval compare` variants to include `profile` field that maps to profile factory.

Example config:

```toml
provider = "fake"
profile = "tiny-pi"
tool_surface = "pi-minimal"
```

Add render section:

```text
## Profile Metrics
- static_prompt_tokens
- tool_schema_tokens
- context_token_estimate
- solve_rate
```

## Cases

Create small eval suites:

1. Read-only explanation.
2. Single-file patch.
3. Multi-file patch.
4. Test failure debug.
5. Large command output recovery.
6. Policy denied network command.
7. Dirty workspace edit.
8. Non-git workspace edit.
9. Skill usage optional case.
10. ContextFS recovery case.

## Exit criteria

- Profile comparison report exists.
- `tiny-pi` has measurable token reduction.
- Any solve-rate drop is visible and discussed.
- Profile-specific failures are categorized.

## Why this matters

This is how tinyagent keeps the Pi philosophy honest. Minimal is good only if it preserves enough capability for the intended use.
