# tinyagent

Minimal local coding-agent runtime.

## Development

```bash
uv run pytest
uv run ruff check .
uv run scripts/size_report.py --export /tmp/tinyagent-code-export.md
```

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
