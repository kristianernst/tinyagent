# Source Boundaries

Generated on 2026-05-24 from the local `tinyagent` worktree plus source archives and local checkouts listed below. Scores in this directory are source-backed where source exists. Cursor and Claude have partial public source boundaries, so their product-level conclusions are marked accordingly.

## Primary Sources Inspected

| Harness | Source inspected | Source boundary |
| --- | --- | --- |
| tinyagent | Local repo at `/Users/kristianernst/work/dev/tinyagent` | Full local source. |
| OpenAI Codex | `https://github.com/openai/codex`, tarball fetched from `https://api.github.com/repos/openai/codex/tarball/main`, extracted at `/private/tmp/tinyagent-harness-compare/openai-codex` | Full public CLI/core/app-server source for the inspected branch. |
| Pi | Local checkout at `/Users/kristianernst/tools/pi-extensions/pi`, package repo points to `https://github.com/earendil-works/pi-mono` | Full local source for the inspected checkout. Worktree had unrelated untracked `ussie.md`; not touched. |
| OpenCode | `https://github.com/sst/opencode`, tarball fetched from `https://api.github.com/repos/sst/opencode/tarball/dev`, extracted at `/private/tmp/tinyagent-harness-compare/opencode` | Full public source for the inspected dev branch. |
| Hermes Agent | `https://github.com/NousResearch/hermes-agent`, tarball fetched from `https://api.github.com/repos/NousResearch/hermes-agent/tarball/main`, extracted at `/private/tmp/tinyagent-harness-compare/hermes-agent` | Full public source for the inspected branch. |
| Cursor SDK | `https://github.com/cursor/plugins/tree/main/cursor-sdk`, tarball fetched from `https://api.github.com/repos/cursor/plugins/tarball/main`, extracted at `/private/tmp/tinyagent-harness-compare/cursor-plugins` | Public plugin/skill docs for `@cursor/sdk`; Cursor IDE/agent runtime implementation is not public here. |
| Claude Code / Agent SDK | `https://github.com/anthropics/claude-code` and `https://github.com/anthropics/claude-code-sdk-python`, extracted at `/private/tmp/tinyagent-harness-compare/claude-code` and `/private/tmp/tinyagent-harness-compare/claude-code-sdk-python` | Claude Code repo contains docs, plugins, examples, settings, issue assets; core CLI implementation is not public. Python Agent SDK source is public. |

## Existing Tinyagent Context

The repo already had high-level landscape notes in:

- `docs/tinyagent_design_spec/02_landscape_research.md`
- `docs/tinyagent_design_spec/03_tradeoff_map.md`
- `docs/tinyagent_design_spec/appendices/current_tinyagent_findings.md`

This comparison goes deeper on source internals and uses `/comparison` as the re-auditable report location.

## Score Meaning

Scores are 1 to 5:

- `5`: strong, source-backed implementation with mature boundaries.
- `4`: strong coverage with smaller gaps or product-specific coupling.
- `3`: usable but incomplete, thinner, or less cleanly separated.
- `2`: weak coverage, mostly product claim, or high coupling.
- `1`: absent or contrary to the design goal.

Do not read the scoreboard as a single winner ranking. It separates harness qualities that pull in different directions: minimality, product breadth, safety, source auditability, and learning/automation.
