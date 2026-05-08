# Stage 1a — HookRunner Extraction

## Problem

Hook invocation logic is duplicated in `Kernel`. Each hook method loop emits `hook.started`, catches exceptions, emits `hook.failed`, handles error policy, and emits `hook.completed`. The repetition makes `Kernel` bulky and makes future hook additions error-prone.

## Target design

Add `tinyagent/core/hook_runner.py`.

```python
class HookRunner:
    def __init__(self, hooks: Sequence[TinyHook], *, error_policy: HookErrorPolicy) -> None: ...

    def call_void(self, state: RunState, method_name: str, *args) -> None: ...

    def transform(self, state: RunState, method_name: str, value, *args): ...

    def transform_pair(self, state: RunState, method_name: str, left, right, *args) -> tuple[list, list]: ...

    def before_tool_call(
        self,
        state: RunState,
        call: ToolCall,
        decision: PolicyDecision,
    ) -> ToolCall | ToolResult | None: ...
```

## Semantics

For each hook where the target method is callable:

1. compute hook name using same logic as `_hook_name`;
2. emit `hook.started` with hook name and method;
3. call method;
4. on exception, emit `hook.failed`, then apply error policy;
5. on success, emit `hook.completed`;
6. preserve hook order.

For transform methods:

- `transform` passes current value and replaces it with returned value;
- `transform_pair` expects `(left, right)` and replaces both only when returned tuple length is 2;
- `before_tool_call` preserves current semantics: current starts as `call`; if a hook returns `ToolResult`, stop and return it; if it returns `ToolCall`, continue with that call; if it returns `None`, keep current.

## Code migration

In `Kernel.__init__`:

```python
self.hook_runner = HookRunner(self.hooks, error_policy=self.hook_error_policy)
```

Replace:

```python
self._run_hooks(state, "on_run_start", state)
```

with:

```python
self.hook_runner.call_void(state, "on_run_start", state)
```

Replace `_on_context`, `_after_model_response`, `_before_model_call`, `_before_tool_call`, `_after_tool_result`, and `_before_finish` bodies with `HookRunner` calls.

## Tests

### Hook success events

Given two hooks with `on_run_start`, assert event sequence:

```text
hook.started hook=a method=on_run_start
hook.completed hook=a method=on_run_start
hook.started hook=b method=on_run_start
hook.completed hook=b method=on_run_start
```

### Transform context

Hook appends a context message. Assert transformed context used in model request and hook events emitted.

### Transform pair

Hook removes a visible tool. Assert `context.built` / model call sees changed tool list.

### Before tool returns ToolResult

Hook blocks tool with synthetic result. Assert no executor call, tool result recorded, hook events emitted.

### Before tool mutates ToolCall

Hook changes args. Assert policy re-evaluated after mutation and executor sees mutated call.

### Error policy fail

Hook raises. Assert `hook.failed`, run failed, exception boundary behavior consistent.

### Error policy record

Hook raises. Assert `hook.failed`, run continues.

## Exit criteria

- All hook behavior tests pass before and after extraction.
- `Kernel` no longer has duplicated hook loops.
- No event payload shape changes.

## Why this is the first refactor

It is narrow, mechanical, and high-leverage. It makes `Kernel` visibly cleaner while preserving the run loop.
