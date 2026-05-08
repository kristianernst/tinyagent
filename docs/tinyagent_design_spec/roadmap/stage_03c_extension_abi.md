# Stage 3c — Extension ABI

## Problem

Tinyagent already has an `Extension` protocol that can provide hooks, tools, skills, and context sources. This is a good start, but the ABI should be clarified before extensions become more important.

## Target design

Keep the ABI small:

```python
class Extension(Protocol):
    name: str
    def hooks(self) -> Sequence[TinyHook]: ...
    def tools(self) -> Sequence[Tool]: ...
    def skills(self) -> Sequence[SkillSource]: ...
    def context_sources(self) -> Sequence[ContextSource]: ...
```

Add optional metadata without forcing every extension to implement it:

```python
@dataclass(frozen=True)
class ExtensionInfo:
    name: str
    version: str = ""
    description: str = ""
    permissions: tuple[str, ...] = ()
```

Optional method:

```python
def info(self) -> ExtensionInfo: ...
```

## ABI rules

1. Extensions are loaded before a run starts.
2. A run has a resource snapshot; resources do not mutate mid-run unless future API explicitly supports reload.
3. Extension tools use the same policy and executor path as built-ins.
4. Extension hooks use the same HookRunner and event contract.
5. Extension context sources use the same `context_search` / `context_read` mechanism.
6. Executable project extensions require trust or explicit opt-in.
7. Extension errors are visible through events.

## Permission metadata

An extension can declare permissions it may require:

- `network`;
- `filesystem`;
- `workspace_index`;
- `mcp_server:<name>`;
- `lsp`;
- `secrets`.

This metadata is informational first. Do not build a full permission marketplace. The policy engine still decides per tool call.

## Tests

- Extension tool appears when loaded.
- Extension hook emits hook events through HookRunner.
- Extension skill source appears in skill registry.
- Extension context source appears in dynamic sources only for profiles that expose context tools.
- Untrusted executable extension is rejected or ignored by default.

## Exit criteria

- ABI documented.
- Extension loading has trust behavior.
- Built-in MCP/LSP/todo extensions still work.
- `tiny-pi` can run with no extensions loaded.

## Why this matters

The project should be extensible without becoming framework-heavy. A small ABI lets users add power while the default remains lean.
