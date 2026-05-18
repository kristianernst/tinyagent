# TinyAgent TUI Implementation Plan

This file tracks the implementation sequence from `docs/goals/tui.md`.

## Gate 1: Foundation

- Remove the React/Vite `chatui/` product surface.
- Add `tui/` as the Bun/OpenTUI client package.
- Add protocol docs and design tokens.
- Normalize `/v1` workspace, git, conversation, approval, cancellation, artifact, and fork endpoints.
- Export the surface schema for TypeScript.
- Add reducer, SSE parser, client, fixtures, and tests.

Gate check:

```bash
uv run pytest tests/test_runtime.py tests/test_kernel.py
uv run ruff check .
bun test
bun run build
```

## Gate 2: TUI Shell

- `tinyagent-tui --server ...` connects to `/v1/health`.
- `tinyagent-tui --workspace . --provider fake` spawns `tinyagent serve --port 0`.
- `tinyagent tui` is a Python-only thin launcher.
- No OpenTUI or Bun dependency is added to `pyproject.toml`.

## Gate 3: Event Experience

- Pure reducer handles run lifecycle, streamed text, reasoning, tools, approvals, artifacts, diffs, usage, failure, and cancellation.
- Fixtures cover success, tools, approval, diff, failure, and large replay.
- Components render from reducer state.

## Gate 4: Control Surface

- Command palette exposes `/new`, `/sessions`, `/resume`, `/fork`, `/rewind`, `/context`, `/model`, `/plan`, `/build`, `/always-approve`, `/ask`, `/compact`, `/usage`, `/theme`, `/stop`, `/diff`, `/review`, `/eval`, `/skills`, `/memory`, `/debug`, `/headless`, `/acp`, and `/help`.
- Plan mode is backend-enforced through `session_mode=plan`.
- Approval and cancellation use `/v1` endpoints.

## Gate 5: Release Readiness

- Large diffs are intentionally truncated.
- 10k event replay stays bounded and deterministic.
- Headless JSONL remains first-class.
- JSON-RPC/ACP work stays additive and does not disturb HTTP/SSE.
