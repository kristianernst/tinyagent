# Tinyagent Lean Harness Design Pack

This pack crystallizes the next design direction for tinyagent. It is written for a tinygrad-like philosophy: a small number of powerful primitives, explicit traces, file-backed state, minimal default surface, and extension points that do not bloat the core.

## Reading order

Start with these files:

1. `00_executive_summary.md` — final recommendation and ordering.
2. `01_design_philosophy.md` — the tinyagent north star.
3. `02_landscape_research.md` — comparison across Pi, Cursor, Codex, Claude Code, OpenCode, Hermes, OpenAI Agents SDK, and broader agent frameworks.
4. `03_tradeoff_map.md` — decision matrix and tradeoff mapping.
5. `04_cross_domain_inspiration.md` — patterns from robotics, control, Unix, tinygrad, and design.
6. `05_refactor_argument.md` — why these refactors, why this order, and what not to build.
7. `06_target_architecture.md` — module-level target architecture.
8. `roadmap/00_roadmap_overview.md` — staged implementation plan.

The roadmap directory then contains one detailed file for every stage and substage. Each stage file gives the full implementation frame. Each substage file is intended to be directly actionable by an engineer.

## Roadmap structure

Stage 0 fixes safety and correctness before aesthetics.

Stage 1 makes `Kernel` smaller without hiding trace boundaries.

Stage 2 makes ContextFS leaner by separating render planning from safety/path policy.

Stage 3 adds a Pi-style lean default profile and a small extension/resource loader.

Stage 4 upgrades the SDK and HTTP protocol without turning tinyagent into a product monolith.

Stage 5 makes the harness eval-driven and regression-resistant.

Stage 6 adds optional memory and self-improvement, but only through review-gated files and skills.

Stage 7 defines future product surfaces while keeping the kernel minimal.

## Design claim

Tinyagent should not become a clone of Cursor, Codex, Claude Code, OpenCode, Hermes, LangGraph, or Pi. The best target is narrower:

> Tinyagent is a lean, traceable, local-first agent kernel with file-backed context and explicit extension seams.

The core should be small enough that one engineer can understand it end-to-end, yet expressive enough that product shells, IDEs, cloud runners, custom tools, skills, and eval harnesses can all be built around it.

## Most important immediate decisions

The first work should not be “more agent features.” It should be boundary hardening and simplification:

1. Fix artifact exposure and approval-step closure.
2. Extract `HookRunner` from `Kernel` with event-output tests.
3. Convert ContextFS rendering into a pure render plan while keeping safety functions explicit.
4. Add `tiny-pi` as a deliberately small profile: read, write, edit, bash; optional grep/find/ls; no default MCP/LSP/todo injection.
5. Make SDK runs cancellable and approval-aware.
6. Add event/schema/eval gates that protect the trace contract.

See `roadmap/00_roadmap_overview.md` for details.
