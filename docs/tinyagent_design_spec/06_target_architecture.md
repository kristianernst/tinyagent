# Target Architecture

## Overview

The target architecture keeps the current explicit run loop but moves repeated boundary logic into small helpers. It does not introduce a graph runtime, database, or product framework.

```text
            +----------------+
            |    Profile     |
            | prompt/tools   |
            | finish/compact |
            +-------+--------+
                    |
                    v
+--------+   +------+-------+   +---------------+
| Model  |<->|    Kernel    |<->| HookRunner    |
+--------+   | orchestration|   +---------------+
             +------+-------+
                    |
                    v
             +------+-------+
             | ToolDispatch |
             | guard/run/log|
             +------+-------+
                    |
        +-----------+------------+
        |                        |
        v                        v
+-------+-------+        +-------+-------+
| Policy/Safety |        |   Executor    |
+---------------+        +---------------+
        |                        |
        +-----------+------------+
                    v
             +------+-------+
             |   RunState   |
             | events/state |
             +------+-------+
                    |
          +---------+----------+
          |                    |
          v                    v
 +--------+--------+   +-------+---------+
 | ContextFS files |   | Artifacts/JSONL |
 +-----------------+   +-----------------+
```

## Core module responsibilities

### `Kernel`

Owns the high-level loop only:

- create/prepare `RunState`;
- emit run lifecycle events;
- start turns;
- ask profile for visible tools/context;
- call model provider;
- pass tool calls to dispatcher;
- handle finish gate;
- finalize outputs.

`Kernel` should not manually repeat hook-running patterns or ContextFS rendering details.

### `HookRunner`

Owns lifecycle hook execution and trace events.

Required methods:

```python
class HookRunner:
    def call_void(self, state: RunState, method: str, *args) -> None: ...
    def transform(self, state: RunState, method: str, value, *args): ...
    def transform_pair(self, state: RunState, method: str, left, right, *args): ...
    def before_tool_call(
        self,
        state: RunState,
        call: ToolCall,
        decision: PolicyDecision,
    ) -> ToolCall | ToolResult | None: ...
```

Invariants:

- emits `hook.started` before each called hook method;
- emits `hook.completed` on success;
- emits `hook.failed` on exception;
- honors `hook_error_policy` exactly;
- preserves hook order;
- does not know policy or model semantics.

### `ToolDispatcher`

Optional after `HookRunner`. If extracted, owns guarded tool dispatch:

1. unknown tool guard;
2. visibility guard;
3. progress guard;
4. policy evaluation;
5. before-tool hooks;
6. approval resolution;
7. deny/block result construction;
8. execution start events;
9. executor run;
10. after-tool hooks;
11. workspace delta capture;
12. transcript/observation/event recording;
13. ContextFS refresh;
14. step closure.

The dispatcher should be extracted only after event invariants are in place.

### `ContextFsRenderer`

Owns file content rendering only.

```python
@dataclass(frozen=True)
class ContextFileSpec:
    rel: str
    section: str
    title: str
    description: str
    render: Callable[[RunState], str]
    include_in_index: bool = True
    static_allowed: bool = True

@dataclass(frozen=True)
class ContextIndexEntry:
    path: str
    section: str
    description: str
    read_hint: str = ""
```

Responsibilities:

- build static file specs;
- render index from specs and dynamic entries;
- render task/environment/status/diff/failure/observations/transcript/history;
- write tool docs and diff docs through explicit helpers.

Non-responsibilities:

- path resolution;
- artifact exposure;
- public/private artifact policy;
- ContextFS read permission;
- secret/path sanitization rules, except by calling shared sanitizers.

### `ContextFS` policy surface

The current `contextfs.py` can remain the public safety/path surface:

- `resolve_context_path`;
- `allowed_context_read_paths`;
- `artifact_kind`;
- `relative_output_path`;
- `model_readable_path` or replacement stable-ref formatter;
- hidden path filtering;
- sanitization helpers.

This should be explicit and test-heavy.

### `ResourceLoader`

Inspired by Pi’s resource loader. It should discover optional resources without making `Kernel` discover them.

Potential API:

```python
@dataclass(frozen=True)
class LoadedResources:
    extensions: tuple[Extension, ...] = ()
    skill_sources: tuple[SkillSource, ...] = ()
    prompt_templates: tuple[PromptTemplate, ...] = ()
    context_files: tuple[ContextFile, ...] = ()

class ResourceLoader:
    def load(self, workspace: Path, profile: str) -> LoadedResources: ...
```

Discovery should be profile-controlled:

- `tiny-pi` can load minimal project/user resources;
- `tiny-coder` can load broader extensions;
- product server can configure explicit resources.

### Profiles

Profiles should become the main expression of workflow philosophy.

Minimum profiles:

| Profile | Purpose | Default tools |
| --- | --- | --- |
| `tiny-pi` | Minimal primitive harness | read, edit/write, shell; optional grep/find/ls. |
| `tiny-coder` | Current robust coding harness | current broader tool surface. |
| `tiny-safe` | Locked-down/local safety | read/search, edits gated, restricted shell. |
| `tiny-codex` | OpenAI/Codex-style patch harness | patch-first, preamble-friendly, strict diff/test. |
| `tiny-claude` | Claude-style str_replace harness | string-edit-first, natural language tool use. |

Only `tiny-pi` and current `tiny-coder` need to be implemented immediately.

### SDK

Target SDK shape:

```python
agent = Agent(
    workspace=".",
    provider=provider,
    profile="tiny-pi",
    resources=ResourceLoader.default(),
)

run = await agent.start("fix the parser")

async for event in run.events():
    ...

await run.cancel("user_cancelled")
result = await run.result()
```

Required concepts:

- `RunHandle`;
- `RunResult`;
- `ApprovalRequest` callback or async queue;
- cancellation token;
- public artifact listing/access;
- event iteration that ends on terminal event;
- replay/fork helper.

### Runtime protocol

Unify route logic around a resolver:

```python
class RunResolver(Protocol):
    def controller_for_run(self, run_id: str, *, workspace_id: str | None = None) -> RunController: ...
    def controller_for_workspace(self, workspace_id: str) -> RunController: ...
```

Then implement one route layer for:

- list runs;
- get run;
- stream events;
- list events JSON;
- list public artifacts;
- fetch public artifact;
- cancel run;
- resolve approval;
- fork run.

Product mode only adds workspace registration and product-specific listing.

## Event contract

The event stream is the system’s main public truth. It should have tests for:

- monotonic `seq`;
- terminal event exactly once;
- turn start/finish closure;
- step start/finish closure;
- tool call/result transcript pairing;
- policy decision before execution;
- hidden/internal events not surfaced by default;
- artifact created before public artifact listing;
- workspace mutation event after mutating tool;
- contextfs update after tool/finalization.

## Artifact contract

Artifacts should be classified:

| Artifact kind | Default public? | Examples |
| --- | ---: | --- |
| Run output | Yes | `final.md`, `final.diff`, public summaries. |
| Model request | No | model logical/http requests. |
| Model response | No by default | raw model response. |
| Context report | No by default | context-report JSON. |
| ContextFS | No through artifact API; readable through context policy | `context/*`. |
| Workspace delta | Maybe yes when safe | final/changed diff artifacts. |
| Skill loaded | Maybe yes | loaded skill artifact if safe. |

Legacy routes and v1 routes must enforce the same visibility.

## Context contract

The model should see:

- system/profile prompt;
- task;
- environment envelope;
- project instructions if small;
- dynamic source list;
- ContextFS index pointer;
- recent tool results selected by profile/context plan.

The model should not see by default:

- raw model request artifacts;
- full event log;
- all MCP schemas;
- all skills;
- all prior conversations;
- all command output;
- hidden paths/secrets;
- product home absolute paths.

## Extension contract

Extensions can provide:

- tools;
- hooks;
- skills;
- context sources;
- optional profiles;
- policy rules in future.

Extensions should not mutate core registries after run start unless explicitly supported. A run should have a reproducible resource snapshot.

## Target repo qualities

After the roadmap, the repo should have:

- smaller `Kernel`;
- smaller or split ContextFS rendering;
- stable event tests;
- consistent artifact safety;
- lean `tiny-pi` profile;
- cancellable SDK;
- unified route handling;
- profile comparison evals;
- optional skill-draft learning path.

That is enough to make tinyagent feel intentionally lean rather than merely incomplete.
