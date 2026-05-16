# Coding Harness Stress Example

This example is a hard, local coding-agent task for stressing context selection,
tool use, file edits, verification, and final-diff behavior. The suite contains
an artificial repo with a deliberately incomplete multi-file Python CLI app.

Run it through the normal eval harness:

```bash
uv run tinyagent eval examples/coding_stress \
  --provider openai-compatible \
  --workspace-mode current \
  --sandbox-mode container \
  --profile tiny-coder \
  --stream text \
  --debug 1 \
  --output-dir /tmp/tinyagent-coding-stress
```

For a local OpenAI-compatible server, set the usual provider env vars first:

```bash
export TINYAGENT_MODEL_BASE_URL=http://127.0.0.1:8080/v1
export TINYAGENT_MODEL_API_KEY=local
export TINYAGENT_MODEL_NAME=<model-id>
```

If the default container image is too small for your local setup, build or point
at an image that has Python, git, sed, and rg available, then rerun:

```bash
export TINYAGENT_CONTAINER_IMAGE=tinyagent-coding-sandbox:local
```

The useful artifacts after a run are:

- `<output-dir>/results.jsonl`
- `<output-dir>/report.md`
- `<output-dir>/comparison.json` and `<output-dir>/comparison.md` when using
  `tinyagent eval compare`
- `<output-dir>/workspaces/build-refactor-planner`
- `<output-dir>/runs/build-refactor-planner/events.jsonl`
- `<output-dir>/runs/build-refactor-planner/artifacts/context-report-*.json`
- `<output-dir>/validation/build-refactor-planner.txt`

The eval report includes observed provider/protocol/adapter, model-call count,
tool-call count, safe parallel batch count, and provider-reported input,
cached-input, output, reasoning, and total tokens when the provider reports
usage.

The task prompt lives in
`build-refactor-planner/task.json`, with the detailed implementation brief inside
the fixture repo at `docs/IMPLEMENTATION_BRIEF.md`.
