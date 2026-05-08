# Roadmap Overview

## Roadmap purpose

This roadmap turns the design philosophy into concrete engineering work. The ordering is intentionally conservative: correctness and event contracts first, elegance second, product features later.

The implementation should proceed in small PRs. Each PR should either fix a boundary, reduce a repeated pattern, or add a clearly isolated capability. Avoid “grand refactor” PRs.

## Stage summary

| Stage | Name | Purpose | Main outcome |
| ---: | --- | --- | --- |
| 0 | Safety and correctness boundary fixes | Repair known risk points before refactoring | Hidden artifacts protected, approval steps close, ContextFS edge cases covered. |
| 1 | Lean Kernel boundary | Remove repeated hook logic and prepare tool dispatch cleanup | `Kernel` becomes shorter without changing loop semantics. |
| 2 | ContextFS render plan | Separate file rendering from safety/path policy | ContextFS remains file-first but less bulky. |
| 3 | Pi profile and extensibility | Add minimal profile and resource loading seams | Lean default path exists without deleting robust profile. |
| 4 | SDK and protocol | Make programmatic usage stable and cancellable | `RunHandle`, approvals, route unification, schema discipline. |
| 5 | Eval-driven harness | Protect taste and trace behavior with metrics | Profile comparisons and event invariants catch regressions. |
| 6 | Optional memory and self-improvement | Add Hermes-inspired learning without core opacity | Review-gated skill draft loop. |
| 7 | Product surface future | Define TUI/IDE/cloud/multi-agent surfaces around kernel | Product expansion without kernel bloat. |

## Dependency order

```text
Stage 0
  ├── Stage 1
  │    └── optional ToolDispatcher cleanup
  ├── Stage 2
  │    └── Stage 3 tiny-pi profile
  └── Stage 4 route/SDK correctness
       └── Stage 7 product surfaces

Stage 5 starts after Stage 0 and expands with every later stage.
Stage 6 starts only after skills, evals, and artifacts are stable.
```

## Non-negotiable engineering rules

1. Every stage must preserve or intentionally version durable event output.
2. Every stage must add tests before or with implementation.
3. Default `tiny-pi` must remain lean; features should not leak into it by default.
4. Any route that exposes artifacts must use one public-artifact policy path.
5. Any new extension capability must be optional and discoverable.
6. No stage may introduce a database dependency into the core kernel.
7. No stage may introduce a graph runtime into the core kernel.
8. Every stage must define exit criteria.

## Recommended branch / PR sequence

1. `s0-artifact-boundary-tests`
2. `s0-artifact-boundary-fix`
3. `s0-approval-step-closure`
4. `s0-contextfs-edge-tests`
5. `s1-hookrunner-tests`
6. `s1-hookrunner-extract`
7. `s1-tool-dispatch-invariants`
8. `s2-contextfs-render-specs`
9. `s2-contextfs-stable-refs`
10. `s3-tiny-pi-profile`
11. `s3-resource-loader`
12. `s4-sdk-runhandle`
13. `s4-approval-callbacks`
14. `s4-route-unification`
15. `s5-event-invariants`
16. `s5-profile-eval-matrix`
17. `s6-skill-draft-pipeline`
18. `s7-product-shell-planning`

## Stage files

Stage-level files:

- `stage_00_safety_fixes.md`
- `stage_01_lean_kernel.md`
- `stage_02_contextfs_render_plan.md`
- `stage_03_pi_profile_extensibility.md`
- `stage_04_sdk_protocol.md`
- `stage_05_eval_driven_harness.md`
- `stage_06_optional_memory_self_improvement.md`
- `stage_07_product_surface_future.md`

Substage files:

- `stage_00a_public_artifact_boundary.md`
- `stage_00b_approval_step_closure.md`
- `stage_00c_contextfs_safety_edges.md`
- `stage_01a_hook_runner.md`
- `stage_01b_tool_dispatch_pipeline.md`
- `stage_01c_event_contract_tests.md`
- `stage_02a_context_file_specs.md`
- `stage_02b_stable_refs_no_absolute_paths.md`
- `stage_02c_contextfs_search_read_edges.md`
- `stage_03a_tiny_pi_profile.md`
- `stage_03b_resource_loader.md`
- `stage_03c_extension_abi.md`
- `stage_04a_cancellable_sdk_run_handle.md`
- `stage_04b_approval_callback_api.md`
- `stage_04c_route_unification_v1_schema.md`
- `stage_05a_event_invariant_tests.md`
- `stage_05b_profile_eval_matrix.md`
- `stage_05c_trace_mining_metrics.md`
- `stage_06a_skill_draft_learning_loop.md`
- `stage_06b_memory_as_files.md`
- `stage_06c_self_evolution_out_of_tree.md`
- `stage_07a_tui_server_split.md`
- `stage_07b_multi_agent_coordination_files.md`
- `stage_07c_remote_backend_contract.md`

## Definition of done for the whole roadmap

The roadmap is complete when:

- the public artifact boundary is enforced consistently;
- `Kernel` hook execution is extracted and event-tested;
- ContextFS rendering is driven by specs/plans rather than inline monolith rendering;
- `tiny-pi` and `tiny-coder` are both first-class profiles;
- SDK runs can be cancelled and can resolve approvals;
- runtime/product routes share one artifact/event implementation;
- profile comparison evals exist;
- optional skill learning creates reviewable drafts rather than hidden memory;
- product expansion is possible without touching the core loop.
