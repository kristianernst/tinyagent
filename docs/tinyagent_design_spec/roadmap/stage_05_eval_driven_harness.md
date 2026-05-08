# Stage 5 — Eval-Driven Harness

## Goal

Make tinyagent’s design philosophy measurable. The harness should be changed by evidence, not taste alone.

## Why this is necessary

Agent harness improvements are subtle. A change can reduce token count but hurt solve rate. A stronger finish gate can improve truthfulness but cause loops. A minimal tool surface can improve clarity but increase shell misuse. Only evals and event invariants can keep these tradeoffs honest.

## Substages

1. `stage_05a_event_invariant_tests.md`
2. `stage_05b_profile_eval_matrix.md`
3. `stage_05c_trace_mining_metrics.md`

## Primary changes

- Add event invariant checker if not already completed in Stage 1c.
- Add profile comparison runner for `tiny-pi` vs `tiny-coder`.
- Add prompt/tool token metrics.
- Add context bloat metrics.
- Add safety route tests to normal CI.
- Add trace mining summaries for tool failures, repeated commands, finish gate interventions, and context usage.

## Eval dimensions

| Dimension | Metric |
| --- | --- |
| Capability | solve rate, validation pass rate. |
| Lean surface | static prompt tokens, tool schema tokens. |
| Context behavior | context token estimate, ContextFS reads, context search count. |
| Safety | policy denials, sandbox blocks, approval requests. |
| Discipline | diff-after-edit, verification-after-edit, false test claim blocks. |
| Efficiency | model calls, tool calls, repeated commands, duration. |
| Robustness | unknown tool errors, invalid tool args, finish gate loops. |

## Exit criteria

- `tiny-pi` and `tiny-coder` comparison report exists.
- Event invariant checker runs in tests or evals.
- Roadmap stages have measurable exit gates.
- No future major refactor can merge without event/safety tests.

## Why this matters

Tinygrad-like minimalism is not aesthetic minimalism. It is functional compression. Evals help distinguish compression from underbuilding.
