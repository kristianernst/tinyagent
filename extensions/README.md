# Extensions

Extensions are executable runtime modules.

An extension may eventually register tools, hooks, providers, policy behavior,
context sources, replay behavior, or command/UI surfaces. Do not put skills,
prompt templates, MCP server definitions, or packages here just because they add
capability.

tinyagent now exposes a minimal explicit extension host. Project-local Python is
not loaded automatically; callers must opt in by constructing extension objects
or by calling `tinyagent.core.extensions.load_extension_file(path)` and passing the
result to `Kernel(..., extensions=[...])`.

An extension object exposes hooks and tools:

```python
class MyExtension:
    name = "my-extension"

    def hooks(self):
        return [my_hook]

    def tools(self):
        return [my_tool]
```

Extension tools follow the normal visibility rule: registering a tool does not
make it callable unless the active profile includes it in the model-visible
tool list. Hook failures follow the kernel's `hook_error_policy`.
