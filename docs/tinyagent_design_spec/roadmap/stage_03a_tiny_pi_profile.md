# Stage 3a — `tiny-pi` Profile

## Problem

The current default profile is powerful but not minimal. It exposes many tools and context concepts by default. This makes tinyagent less aligned with a Pi/tinygrad-like philosophy.

## Target design

Add a `TinyPiProfile` with a smaller prompt and smaller visible tool surface.

Possible implementation:

```python
class TinyPiProfile:
    name = "tiny-pi"
    profile_variant = "minimal"
    context_policy_name = "pi-v1"
    tool_surface_name = "pi-minimal"
```

Alternative: implement as a variant of `ApexCoderProfile`. Prefer a separate class initially if it keeps conditionals out of the existing profile.

## Prompt principles

The prompt should say only what is necessary:

- you are a coding agent in this workspace;
- inspect before editing when needed;
- use shell for commands;
- use edit tool for file changes;
- keep outputs concise;
- do not claim tests passed unless you ran them;
- respect policy/sandbox messages;
- finish with what changed and what was verified.

Do not inject large explanations of ContextFS, skills, MCP, LSP, todo memory, or eval machinery.

## Tool surface

Minimum:

```python
DEFAULT_VISIBLE_TOOL_NAMES = (
    "read_file",
    "apply_patch",   # or model-specific edit tool
    "shell",
)
```

Potential optional additions:

- `list_files` if shell `find`/`ls` friction hurts evals;
- `search_code` only if it is materially better than `rg` and does not bloat prompt;
- `context_read` only if ContextFS recovery is needed after long outputs.

Recommended starting point:

- include `read_file`, `shell`, edit tool;
- include `list_files` only if current eval cases need it;
- do not include `context_search`, `context_read`, `list_skills`, `load_skill`, MCP, LSP, or todo by default.

## Context builder

Use a simpler context builder or a mode in `ContextBuilder`:

- system prompt;
- environment context, smaller than current;
- project instructions;
- task;
- recent tool results tail;
- optional ContextFS index path only after tool outputs/artifacts exist.

Avoid static dynamic context source list.

## Finish behavior

Pi-like mode should not over-police. But it should enforce truthfulness:

- block final answer if it claims tests/checks passed without verification evidence;
- mention policy/sandbox limitations if encountered;
- if edits occurred, encourage but do not always hard-block diff/test unless `tiny-safe` or `tiny-coder`.

Maybe implement two variants:

| Variant | Finish gate |
| --- | --- |
| `tiny-pi` | Minimal truthfulness only. |
| `tiny-pi-safe` | Requires diff/inspection and verification after edits. |

Start with `tiny-pi` and keep current `tiny-coder` as the stricter profile.

## CLI/API changes

Add profile selection:

```text
tinyagent run --profile tiny-pi "..."
tinyagent serve --profile tiny-pi
```

Add registry:

```python
def profile_for(name: str, *, model_spec=None, config=None) -> Profile: ...
```

## Tests

- Profile visible tools are minimal.
- Prompt token estimate is below configured threshold.
- Claims-tests-passed gate works.
- Edits can complete without mandatory todo/context-source tools.
- Existing `tiny-coder` behavior unchanged.

## Metrics

Track in evals:

- static prompt tokens;
- visible tool schema tokens;
- model calls;
- tool calls;
- solve rate;
- verification rate;
- repeated shell count;
- final answer truthfulness blocks.

## Exit criteria

- `tiny-pi` profile exists and is selectable.
- It runs basic fake provider tests.
- It is materially smaller than `tiny-coder` by token estimate.
- It does not weaken policy/safety boundaries.

## Why this is necessary

The project needs a concrete lean mode. Otherwise “minimal” remains a taste statement rather than a measurable harness variant.
