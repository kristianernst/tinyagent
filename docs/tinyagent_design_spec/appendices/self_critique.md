# Self-Critique and Design Review Notes

This appendix records the critique passes used to stabilize the recommendation. It is intentionally written as a design review artifact, not as private chain-of-thought.

## Pass 1: Minimality audit

Initial temptation: recommend a broad architecture split: `Kernel`, `Dispatcher`, `ContextManager`, `SafetyManager`, `ProtocolManager`, `MemoryManager`, `SkillManager`, and `RunGraph`.

Critique: that would violate the requested tinygrad/Pi direction. It would replace explicit bulk with managerial bulk. The design would look cleaner on paper but add too many concepts.

Revision: only extract `HookRunner` first. Treat `ToolDispatcher` as optional and later. Convert ContextFS rendering into a data plan, not a manager class.

## Pass 2: Safety audit

Initial temptation: focus on elegance targets first because the user specifically mentioned Kernel and ContextFS.

Critique: known boundary bugs should precede elegance. Artifact exposure and approval-step closure are correctness issues. A minimal harness that leaks hidden artifacts is not trustworthy.

Revision: Stage 0 is safety/correctness. No refactor should start before artifact boundary tests pass.

## Pass 3: Context audit

Initial temptation: copy Cursor’s dynamic context more aggressively and make ContextFS the central abstraction for all state.

Critique: ContextFS should be a recovery/read surface, not a state monolith. Too much ContextFS centrality could make the model over-dependent on generated files and increase maintenance burden.

Revision: keep ContextFS focused: model-readable recovery files, public refs, bounded artifacts, and context-source bridge. Do not put every feature into ContextFS.

## Pass 4: Pi philosophy audit

Initial temptation: shrink the current `ApexCoderProfile` directly.

Critique: the current profile has useful robust behavior. Removing tools/features globally would conflate philosophy with capability. It would also prevent an honest A/B comparison.

Revision: add `tiny-pi` as a separate profile. Compare against `tiny-coder` through evals.

## Pass 5: Product surface audit

Initial temptation: recommend TUI/desktop/IDE improvements early because OpenCode/Cursor/Claude make them central.

Critique: product UX should consume a stable SDK/protocol. Building UI before SDK cancellation/approval/routing is premature.

Revision: SDK and route unification before product surface work.

## Pass 6: Memory audit

Initial temptation: recommend Hermes-style learning as a major roadmap item.

Critique: self-improvement is powerful but can be opaque and bloated. It also depends on stable traces, skills, and evals.

Revision: put self-improvement in Stage 6 as optional, review-gated skill drafting, not core memory.

## Pass 7: Evaluation audit

Initial temptation: define roadmap stages as code changes only.

Critique: harness changes regress in ways code review does not catch: token bloat, event drift, policy drift, repeated commands, verification omissions.

Revision: every stage has tests and exit criteria. Stage 5 explicitly strengthens evals and invariants.

## Final design constraints after critique

1. Fix safety before elegance.
2. Prefer narrow extraction over framework introduction.
3. Preserve event output unless deliberately versioned.
4. Keep ContextFS as files, not a virtual filesystem framework.
5. Add a lean profile instead of weakening the robust one.
6. Make SDK/protocol stable before product UX.
7. Keep memory and self-improvement optional and review-gated.
8. Encode taste into evals.

## Rejected designs

### Full graph runtime

Rejected because it adds a major concept before proving need. External orchestration can use events and SDK handles later.

### Built-in subagents

Rejected for now because product-level multi-agent coordination can be implemented with multiple runs and shared files. Kernel-native subagents are not needed for the next stage.

### Default MCP/LSP/todo memory

Rejected because default context/tool bloat conflicts with the Pi profile. They remain extensions.

### Database state

Rejected because JSONL/events/files are sufficient and more inspectable for the current scale.

### Opaque persistent memory

Rejected because it weakens reviewability. Prefer skills and files.

### Native sandbox first

Rejected as first step because artifact/protocol correctness is more urgent and smaller. Native sandboxing is important but not the first refactor.
