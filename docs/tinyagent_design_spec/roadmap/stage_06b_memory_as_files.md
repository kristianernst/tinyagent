# Stage 6b — Memory as Files

## Problem

Run-scoped todo memory exists, but persistent memory is not defined. Adding hidden persistent memory would conflict with the lean design.

## Target design

Represent memory as explicit files:

```text
.tinyagent/memory/
  project.md
  user-notes.md
  decisions.md
  skills-index.md
```

Expose through optional context source:

```text
memory:project
memory:decisions
```

Do not inject memory by default in `tiny-pi`.

## Memory types

| Type | Scope | Default? | Storage |
| --- | --- | ---: | --- |
| Run todo | run | Optional | `context/memory/todo.md` |
| Project memory | workspace | Off by default | `.tinyagent/memory/project.md` |
| User memory | user | Off by default | `~/.tinyagent/memory/user.md` |
| Skill memory | skill | On when skill loaded | `SKILL.md` |
| Conversation history | product workspace | Existing | conversation store/artifacts |

## Commands

```text
tinyagent memory read project
tinyagent memory append project "..."
tinyagent memory open project
```

Approval may be required to write project/user memory depending on trust.

## Tests

- Memory files are excluded from hidden artifact leakage.
- Memory writes require proper path/policy handling.
- Memory context source can search/read when enabled.
- `tiny-pi` does not load memory by default.

## Exit criteria

- Persistent memory exists only as explicit files.
- Memory is optional and profile-controlled.
- No hidden memory state is added to `RunState` beyond refs.

## Why this matters

Files keep memory inspectable, editable, diffable, and removable. That is the correct tinyagent default.
