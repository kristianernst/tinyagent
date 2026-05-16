# Examples

## Web Searcher

`web_searcher.py` is a small web-research agent built on the real tinyagent SDK. It adds two example tools, `web_search` and `fetch_url`, and uses a research profile that forces the run to write `research_report.md` before finalizing. The default fake mode uses deterministic fixture sources so tests can exercise the harness without network access.

Deterministic stock research smoke:

```bash
uv run python examples/web_searcher.py \
  "Do deep research on NVIDIA stock" \
  --provider fake \
  --workspace /tmp/tinyagent-web-stock \
  --stream-events
```

Deterministic flight research smoke:

```bash
uv run python examples/web_searcher.py \
  "Check flight prices from Copenhagen to Tokyo in August" \
  --provider fake \
  --workspace /tmp/tinyagent-web-flight \
  --stream-events
```

Run one live query against the local llama.cpp-compatible endpoint:

```bash
uv run python examples/web_searcher.py \
  "Find the best current sources for whether NVIDIA stock is overvalued after the latest earnings" \
  --provider openai-compatible \
  --base-url http://127.0.0.1:8080/v1 \
  --api-key local \
  --web-backend duckduckgo \
  --workspace /tmp/tinyagent-web-query \
  --run-id query-001 \
  --stream-events
```

Live local llama.cpp run, assuming an OpenAI-compatible server on port 8080:

```bash
uv run python examples/web_searcher.py \
  "Do deep research on NVIDIA stock using current web sources" \
  --provider openai-compatible \
  --base-url http://127.0.0.1:8080/v1 \
  --api-key local \
  --web-backend duckduckgo \
  --workspace /tmp/tinyagent-web-live \
  --stream-events
```

For a llama tool-protocol and context-management smoke without external web access, keep the live model but use fixture sources:

```bash
uv run python examples/web_searcher.py \
  "Check flight prices from Copenhagen to Tokyo in August" \
  --provider openai-compatible \
  --base-url http://127.0.0.1:8080/v1 \
  --api-key local \
  --web-backend fixture \
  --workspace /tmp/tinyagent-web-llama-fixture \
  --stream-events
```

If the llama server requires a specific model string, add `--model <model-id>`. If omitted, the script tries to read the first model id from `/v1/models` and falls back to `local-model`.

The same example can run through Responses providers:

```bash
export TINYAGENT_MODEL_API_KEY=...
uv run python examples/web_searcher.py \
  "Find current sources for whether NVIDIA stock is overvalued after the latest earnings" \
  --provider openai-responses \
  --model gpt-5.5 \
  --web-backend duckduckgo \
  --workspace /tmp/tinyagent-web-responses \
  --stream-events
```

For Codex/ChatGPT subscription auth, sign in with Codex first or provide a refresh-aware token command, then run:

```bash
export TINYAGENT_MODEL_NAME=gpt-5.5-codex
uv run python examples/web_searcher.py \
  "Research Copenhagen to Tokyo August flight prices and booking risks" \
  --provider openai-codex \
  --web-backend duckduckgo \
  --workspace /tmp/tinyagent-web-codex \
  --stream-events
```

The useful artifacts after a run are:

- `<workspace>/research_report.md`
- `<workspace>/.tinyagent/runs/<run-id>/events.jsonl`
- `<workspace>/.tinyagent/runs/<run-id>/metrics.json`
- `<workspace>/.tinyagent/runs/<run-id>/artifacts/context-report-*.json`
- `<workspace>/.tinyagent/runs/<run-id>/artifacts/model-request-http-*.json`
- `<workspace>/.tinyagent/runs/<run-id>/artifacts/model-response-*.json`

## Multirun and Long Context Stress

`web_searcher_multirun.py` runs the same query repeatedly in separate workspaces and writes a machine-readable rollup. This catches flaky tool protocol behavior better than a one-off smoke.

```bash
uv run python examples/web_searcher_multirun.py \
  "Find the best current sources for whether NVIDIA stock is overvalued after the latest earnings" \
  --runs 5 \
  --provider openai-compatible \
  --base-url http://127.0.0.1:8080/v1 \
  --api-key local \
  --web-backend duckduckgo \
  --workspace-root /tmp/tinyagent-web-multirun \
  --continue-on-fail
```

For a single long browse that forces context checkpoints and compaction, increase the source budget and compact aggressively:

```bash
uv run python examples/web_searcher_multirun.py \
  "Research Copenhagen to Tokyo August flight prices, fare timing, route options, and booking risks" \
  --runs 1 \
  --provider openai-compatible \
  --base-url http://127.0.0.1:8080/v1 \
  --api-key local \
  --web-backend duckduckgo \
  --workspace-root /tmp/tinyagent-web-long-browse \
  --max-searches 8 \
  --target-fetches 24 \
  --max-fetches 32 \
  --compact-after-tool-steps 2 \
  --max-turns 80 \
  --max-tool-calls 120 \
  --max-run-seconds 1800 \
  --continue-on-fail
```

The long-browse summary is `<workspace-root>/multirun_summary.json`; inspect each run's `metrics.json`, `events.jsonl`, context checkpoints, and report from the paths printed by the command. Use `--web-backend fixture` for deterministic protocol stress without external network access; it will repeat fixture-backed sources, so it is less meaningful as a web-quality test.
