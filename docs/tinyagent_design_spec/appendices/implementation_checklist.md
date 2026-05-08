# Implementation Checklist

## Stage 0 checklist

- [x] Add tests for hidden artifact listing and fetching.
- [x] Change legacy artifact route to use `public_artifact_path()`.
- [x] Add tests for v1 and legacy artifact consistency.
- [x] Add approval handler exception test.
- [x] Close approval wait step on handler exception.
- [x] Add product-home ContextFS absolute path test.
- [x] Add oversized ContextFS search test.
- [x] Add hidden path sanitization tests.

## Stage 1 checklist

- [x] Add hook event snapshots before extraction.
- [x] Implement `HookRunner`.
- [x] Replace hook loops in `Kernel`.
- [x] Preserve event payloads.
- [x] Add tool-dispatch invariant tests.
- [x] Decide whether to extract `ToolDispatcher` now or defer. Decision: defer a full dispatcher; keep the pipeline invariant-tested while hook extraction stays narrow.

## Stage 2 checklist

- [x] Add ContextFS file snapshots.
- [x] Add `ContextFileSpec`.
- [x] Move pure renderers to `contextfs_render.py`.
- [x] Make `refresh_contextfs()` spec-driven.
- [x] Keep safety/path functions explicit.
- [x] Ensure stable relative refs.
- [x] Verify allowed read paths include generated files.

## Stage 3 checklist

- [x] Add profile registry/factory.
- [x] Implement `tiny-pi` profile.
- [x] Add CLI/runtime profile selection.
- [x] Add minimal prompt snapshot/token estimate.
- [x] Add ResourceLoader.
- [x] Add resource trust behavior.
- [x] Document extension ABI.

## Stage 4 checklist

- [x] Add `RunHandle` and `RunResult`.
- [x] Wire SDK `CancelToken`.
- [x] Add SDK cancellation tests.
- [x] Add approval callback adapter.
- [x] Add route resolver protocol.
- [x] Unify artifact/event routes.
- [x] Expand v1 schema/openapi docs.

## Stage 5 checklist

- [x] Add event invariant checker.
- [x] Add profile eval matrix.
- [x] Add prompt/tool/context token metrics.
- [x] Add trace mining diagnostics.
- [x] Add CI gate coverage for safety/event tests through the repo test suite.

## Stage 6 checklist

- [x] Add skill draft command.
- [x] Generate reviewable `SKILL.md` drafts from traces.
- [x] Add draft install/reject commands.
- [x] Add file-backed memory source.
- [x] Keep memory off by default for `tiny-pi`.
- [x] Add out-of-tree evolution experiment directory.

## Stage 7 checklist

- [x] Define TUI client around SDK events/approvals/artifacts. Current scope: CLI/terminal projection consumes event streams and approval callbacks; richer TUI remains outside the kernel.
- [x] Add backend contract for local/remote runs.
- [x] Prototype multi-agent coordination through shared files.
- [x] Keep Kernel unchanged during product-surface experiments.
