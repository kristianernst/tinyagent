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
tinyagent run "read hello.txt and answer" --provider fake --workspace .
tinyagent replay .tinyagent/runs/<run_id>
tinyagent inspect .tinyagent/runs/<run_id>
tinyagent eval evals/tiny --provider fake
```

For the first disposable real-model spin, use `docs/FIRST_SPIN.md`.

Run artifacts are written under `.tinyagent/runs/<run_id>` by default. Events
store small metadata; larger shell, search, patch, model context, and model
payload data is written under each run's `artifacts/` directory.

## Default tool surface

The default `apex-coder` profile exposes only:

```text
shell
apply_patch
```

Use shell for inspection, search, git, tests, and builds. Prefer `rg`, `rg --files`,
`sed`, `nl`, and normal project commands. Use `apply_patch` for edits. Final
answers are normal assistant content.

Hidden tools such as `read_file`, `list_files`, and `search_repo` may remain
registered for tests or ablations, but the kernel blocks registered tools that
were not visible in the model request that produced the call.

Tool collections are explicit: `builtin_tools()` is `shell` and `apply_patch`,
`repo_inspect_tools()` is the hidden repo-inspection set, and `default_tools()`
currently registers both groups for profile-level visibility control.

Capability/resource categories are defined in `docs/CAPABILITIES.md`. Tools,
MCPs, skills, prompts, and packages are not all extensions.

The `shell` tool runs with `cwd` set to the workspace root and a sanitized minimal
environment. It has a small denylist for obvious destructive commands, but
current Milestone 0+1 YOLO is policy-bounded, not isolation-bounded. It is not a
sandbox and can still access workspace paths unless a stronger executor is added.

Runs record a `ShellPreflight` event/metric for `rg`, `git`, `python3`, `python`,
and `sed` availability.
