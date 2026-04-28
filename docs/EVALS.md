# M1.8 Eval Debug Foundation

Tinyagent evals are local debugging fixtures for the harness, not public
benchmark claims.

Run the bundled tiny suite:

```bash
uv run agentctl eval evals/tiny --provider fake
```

Use a real OpenAI-compatible endpoint:

```bash
uv run agentctl eval evals/tiny \
  --provider openai-compatible \
  --output-dir /tmp/tinyagent-evals/tiny-real
```

Each eval output directory contains:

```text
results.jsonl
report.md
runs/<case-id>/
validation/<case-id>.txt
workspaces/<case-id>/
```

Inspect one run:

```bash
uv run agentctl inspect /tmp/tinyagent-evals/tiny-real/runs/context-read
uv run agentctl replay /tmp/tinyagent-evals/tiny-real/runs/context-read
```

## Case Format

Each case is a directory with a `task.json` and optional `files/` tree:

```text
evals/tiny/context-read/
  task.json
  files/
    hello.txt
```

`task.json`:

```json
{
  "id": "context-read",
  "task": "Inspect hello.txt and return a short final answer.",
  "validation_command": "python3 validate.py",
  "timeout_seconds": 60,
  "setup_git": true
}
```

The runner copies `files/` into an isolated workspace, initializes a git repo by
default, runs Tinyagent, then runs `validation_command` inside the workspace.

## Live Endpoint Integration Tests

The integration tests are skipped by default. To run them against a local
llama.cpp OpenAI-compatible server:

```bash
export TINYAGENT_RUN_INTEGRATION=1
export TINYAGENT_MODEL_BASE_URL=http://127.0.0.1:8080/v1
export TINYAGENT_MODEL_API_KEY=local
export TINYAGENT_MODEL_NAME='unsloth/Qwen3.6-27B-GGUF:Q8_0'
export TINYAGENT_MODEL_TIMEOUT_SECONDS=180
export TINYAGENT_MODEL_EXTRA_BODY_JSON='{"max_tokens":256,"temperature":0}'

uv run pytest tests/integration
```

These tests exercise the real OpenAI-compatible streaming path, a full kernel
streaming trace, and an eval-run smoke against the live endpoint.
