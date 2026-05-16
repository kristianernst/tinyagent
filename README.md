# tinyagent

Minimal local coding-agent runtime.

## Development

```bash
uv run pytest
uv run ruff check .
uv run scripts/size_report.py --export /tmp/tinyagent-code-export.md
```

## Examples

See `examples/README.md` for runnable harness examples, including the web-searcher stress test.

## CLI

```bash
tinyagent run "read hello.txt and answer" --provider fake --workspace .
tinyagent replay .tinyagent/runs/<run_id>
tinyagent inspect .tinyagent/runs/<run_id>
tinyagent eval evals/tiny --provider fake
```

Run artifacts are written under `.tinyagent/runs/<run_id>` by default. Events
store small metadata; larger shell, search, patch, model context, and model
payload data is written under each run's `artifacts/` directory.

## Model Providers

`fake` is deterministic and offline. `openai-compatible` targets
`/v1/chat/completions` servers such as llama.cpp. `openai-responses` targets
OpenAI's `/v1/responses` API:

```bash
export TINYAGENT_MODEL_API_KEY=...
export TINYAGENT_MODEL_NAME=gpt-5.5
tinyagent run "inspect this repo" --provider openai-responses --workspace .
```

`openai-codex` uses the same Responses transport with Codex/ChatGPT bearer auth.
It accepts `TINYAGENT_CODEX_BEARER_TOKEN`, `TINYAGENT_CODEX_AUTH_COMMAND`, or an
unexpired Codex CLI `auth.json` token:

```bash
export TINYAGENT_MODEL_NAME=gpt-5.5-codex
tinyagent run "inspect this repo" --provider openai-codex --workspace .
```

For long-lived runs, prefer `TINYAGENT_CODEX_AUTH_COMMAND` so token refresh stays
owned by a dedicated auth helper instead of depending on a cached CLI token.

`open-responses` targets stateless Responses-compatible local or gateway
servers without assuming OpenAI state/cache features:

```bash
export TINYAGENT_MODEL_BASE_URL=http://127.0.0.1:11434/v1
export TINYAGENT_MODEL_NAME=...
tinyagent run "inspect this repo" --provider open-responses --workspace .
```

`anthropic` and `gemini` use their native tool-calling protocols rather than an
OpenAI-shaped compatibility layer:

```bash
export TINYAGENT_MODEL_API_KEY=...
export TINYAGENT_MODEL_NAME=claude-...
tinyagent run "inspect this repo" --provider anthropic --workspace .

export TINYAGENT_MODEL_API_KEY=...
export TINYAGENT_MODEL_NAME=gemini-...
tinyagent run "inspect this repo" --provider gemini --workspace .
```

## Default tool surface

The default `tiny-coder` profile exposes:

```text
read_file
context_search
context_read
search_code
list_skills
load_skill
shell
apply_patch
```

Use shell for inspection, search, git, tests, and builds. Prefer `rg`, `rg --files`,
`sed`, `nl`, and normal project commands. Use `apply_patch` for edits. Final
answers are normal assistant content.

Hidden tools such as `list_files` may remain registered for tests or ablations,
but the kernel blocks registered tools that were not visible in the model request
that produced the call.

Tool collections are explicit: `builtin_tools()` is `shell` and `apply_patch`,
`repo_inspect_tools()` is the hidden repo-inspection set, and `default_tools()`
currently registers both groups for profile-level visibility control.

The `shell` tool runs with `cwd` set to the workspace root and a sanitized minimal
environment. It has a small denylist for obvious destructive commands, but this
is policy-bounded execution, not a sandbox.

Runs record a `ShellPreflight` event/metric for `rg`, `git`, `python3`, `python`,
and `sed` availability.

## Current Docs

- `docs/PHILOSOPHY.md`
- `docs/MERGE.md`
- `docs/surface-event-contract.md`
