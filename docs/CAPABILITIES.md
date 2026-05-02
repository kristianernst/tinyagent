# Tinyagent Capabilities

Tinyagent keeps the default runtime small, but it should not flatten every future
capability into one `extensions` bucket.

## Resource Types

```text
Builtins:
  Kernel-owned capabilities required by the default harness.

Extensions:
  Executable modules that add or modify runtime behavior.

Skills:
  Markdown instruction packages loaded on demand.

Prompts:
  Reusable slash-command prompt templates.

MCP:
  External capability protocol imported through an adapter extension.

Packages:
  Shareable bundles of extensions, skills, prompts, and config.

Profiles:
  Operating modes that choose what is active and visible.
```

The default `apex-coder` profile exposes only:

```text
shell
apply_patch
```

Other registered tools are internal utilities or ablation candidates unless a
profile explicitly makes them visible.

Tool registration uses explicit groups:

```text
builtin_tools:
  shell, apply_patch

repo_inspect_tools:
  read_file, list_files, search_repo

all_tools/default_tools:
  builtin_tools + repo_inspect_tools
```

The default CLI still registers all tools so ablations can choose visibility from
the profile, but only visible tools can execute.

## Current Classification

| Capability | Type | Default-visible | Notes |
| --- | --- | --- | --- |
| `shell` | builtin tool | yes | Inspect, search, run tests, git, builds. |
| `apply_patch` | builtin tool | yes | File edits with policy, rollback, and trace artifacts. |
| `read_file` | repo-inspect candidate | no | Candidate for file-viewer ablations. |
| `list_files` | repo-inspect candidate | no | Usually redundant with `rg --files` or shell. |
| `search_repo` | repo-inspect candidate | no | Future search should be better than a thin `rg` wrapper. |

When `shell` is registered, Tinyagent records a `ShellPreflight` event and metric
with availability for `rg`, `git`, `python3`, `python`, and `sed`. This records
the intended shell contract without failing the run.

## Invariant

```text
Installed does not mean active.
Active does not mean visible.
Visible does not mean allowed.
Allowed does not mean untraced.
```

Meaning:

```text
Installed:
  A package or resource exists on disk.

Active:
  A profile or config loaded it.

Visible:
  The model could see or call it for the current model request.

Allowed:
  Policy permits this specific action.

Traced:
  The event log records what happened.
```

The kernel enforces the visible-tool boundary before policy and execution.
