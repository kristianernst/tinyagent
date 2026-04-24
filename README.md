# tinyagent

Minimal general-purpose agent harness.

The first implementation slice is Milestone 0+1 from `design/guideline.md`: a small
Python kernel, CLI-first workflow, bounded local execution, JSONL traces, a fake
provider for deterministic tests, and a minimal `apex-coder` profile.

## Development

```bash
uv run pytest
uv run ruff check .
```

## CLI

```bash
agentctl --help
```
