# Stage 5c — Trace Mining Metrics

## Problem

Event logs contain rich information, but current evals only extract a subset. More trace mining can guide harness changes without adding product complexity.

## Target design

Enhance metrics around:

- repeated commands;
- no-progress loops;
- tool error kinds;
- invalid tool args;
- model tool selection errors;
- ContextFS read/search patterns;
- skill load usage;
- time to first edit;
- inspect-before-edit;
- diff-after-edit;
- verification-after-edit;
- final answer claim checks;
- prompt/tool token cost.

## Implementation

Add fields to `RunMetrics`:

```python
static_prompt_tokens: int
tool_schema_tokens: int
model_call_token_estimates: list[int]
time_to_first_tool_seconds: float
time_to_first_edit_seconds: float
unknown_tool_count: int
invalid_tool_args_count: int
approval_request_count: int
hidden_artifact_fetch_failures: int
```

Not all fields must be populated immediately.

## Trace reports

Add a markdown report section:

```text
## Harness Diagnostics
- most repeated commands
- top tool error kinds
- context bloat cases
- finish gate loops
- policy/sandbox blocks
- profile-specific anomalies
```

## Exit criteria

- Eval report makes harness regressions visible.
- Token/context metrics exist for profile comparison.
- Trace mining does not require external services.

## Why this matters

Cursor’s harness posts emphasize continuous harness tuning. Tinyagent can do a local, lean version by mining its own event logs.
