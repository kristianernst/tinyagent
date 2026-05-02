
# Tinyagent PR Checklist

1. Does this add a new concept? If yes, why is an existing concept insufficient?
2. Does this increase kernel LoC? If yes, why does it belong in kernel rather than profile/tool/extension?
3. Can this behavior be replayed from events and artifacts?
4. Does this change model-visible context? If yes, is there a context snapshot test?
5. Does this change capability? If yes, is there a test or eval?
6. Does this change safety policy? If yes, is every decision logged?
7. Can a model understand this file without reading 20 others?
8. Did this remove any code?

## Delete budget

- What code did this delete?
- What concept did this collapse?
- What special case did this remove?

## A great Tinyagent PR is not

Added agent memory subsystem, retrieval service, planner, graph runner, and callback framework.

## A great Tinyagent PR is

Collapsed tool execution and policy logging into one event path.
Deleted 120 LoC.
Added context snapshots.
Improved replay fidelity.

Or:

Refactored profile hooks so verification policy is a 4-line change.
Added golden trace.


## Keep the kernel aggressively small

I would be cautious about these abstractions appearing too early:

Middleware
CallbackManager
WorkflowEngine
GraphNode
Planner
MemoryStore
ToolRegistry with complex lifecycle
ProviderRouter
SessionManager
PluginManager
DependencyContainer
