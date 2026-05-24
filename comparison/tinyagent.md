# tinyagent Scorecard

## Source Boundary

Inspected local source in `/Users/kristianernst/work/dev/tinyagent`, especially:

- `README.md`
- `docs/PHILOSOPHY.md`
- `tinyagent/core/kernel.py`
- `tinyagent/core/state.py`
- `tinyagent/core/events.py`
- `tinyagent/core/policy.py`
- `tinyagent/core/contextfs.py`
- `tinyagent/core/profiles.py`
- `tinyagent/core/sdk.py`

## Design Thesis

Tinyagent is a small event-sourced coding-agent VM. The best part of the design is the hard split between durable events, artifact payloads, policy decisions, and model-readable context. It is closer to a kernel than a product shell.

## Feature Read

| Area | Evidence | Design read |
| --- | --- | --- |
| Event model | `events.py` separates durable events from live-only deltas and covers run, turn, step, workspace, model, tool, policy, approval, context, index, skill, extension, artifact, cancellation. | Strong kernel primitive. Better than most minimal harnesses. |
| Artifacts | `README.md`, `state.py`, `contextfs.py`, and artifact helpers keep large payloads out of event data. | Correct boundary: events are metadata, artifacts are payloads. |
| Policy | `policy.py` gates shell, network-looking commands, secrets, run evidence writes, external redirects, risky commands, repeated failures, dirty workspace edits. | Strong policy layer, but explicitly not a sandbox. |
| Context | `contextfs.py` writes model-readable context files, tool docs, diffs, git status, and allowed refs. | Good dynamic-context direction. Needs clearer public contract. |
| Profiles | `profiles.py` has `ApexCoderProfile` and `TinyPiProfile`, plus finish gates requiring diff/verification evidence after edits. | Profiles are a good way to keep the kernel small while allowing richer behavior. |
| SDK | `sdk.py` exposes async `Agent`, streaming events, cancellation, approval callback, and run result. | Real embedding exists, but thinner than Codex/Cursor/Claude SDK surfaces. |
| Product surface | README/CLI/runtime pieces exist, but no mature IDE/app-server/cloud shell. | Deliberate gap if tinyagent stays kernel-first. |

## Scores

| Dimension | Score |
| --- | ---: |
| Source auditability | 5.0 |
| Kernel clarity/minimality | 5.0 |
| Event/session durability | 5.0 |
| Tool execution/control | 3.5 |
| Permission/sandbox safety | 3.5 |
| Context management | 4.5 |
| Provider/runtime portability | 4.0 |
| Extensibility | 4.0 |
| Product surface/protocol | 2.5 |
| Memory/learning/automation | 2.5 |

## Strengths

- The event/artifact split is the right center of gravity.
- ContextFS gives the model a file-backed way to discover context without loading everything upfront.
- Finish gates tie behavioral claims to evidence, especially after edits.
- The policy layer is concrete and inspectable rather than prompt-only.
- Provider breadth is already broader than a single-vendor harness.

## Weaknesses

- Policy is not enforcement. Native sandboxing is the biggest safety gap versus Codex and Claude.
- Product protocol is not as mature as Codex app-server or OpenCode server surfaces.
- Tool execution is still kernel-heavy in places; Codex/OpenCode have cleaner orchestrator/service separation.
- Learning/memory is deliberately thin; Hermes is far ahead here.
- SDK ergonomics are usable but not yet comparable to Cursor/Claude/Codex for lifecycle inspection, run listing, and remote clients.

## What To Borrow

- From Codex: named permission profiles and native sandbox backend contract.
- From OpenCode: git snapshot/restore model and LSP/product-shell discipline.
- From Pi: keep a tiny default profile and avoid making optional tools default cognitive load.
- From Hermes: only borrow review-gated skill-draft learning, not hidden self-modifying behavior.
- From Claude/Cursor SDKs: richer run lifecycle APIs, status/result taxonomy, and explicit local/cloud/runtime capability checks.
