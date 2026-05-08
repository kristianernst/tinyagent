# Cross-Domain Inspiration

The best design ideas for tinyagent are not only in AI agent repos. They come from Unix, tinygrad, robotics, control theory, physics, and product design.

## Unix: text streams and composable programs

Unix philosophy is the closest ancestor to Pi’s design. The key ideas are simple: small programs, composability, textual interfaces, and early rebuilding of clumsy parts.

### Mapping to tinyagent

| Unix idea | Tinyagent mapping |
| --- | --- |
| Do one thing well | Kernel runs a traced model/tool loop; product shells do UI; extensions add capabilities. |
| Work together | Events, JSONL, markdown, artifacts, and context refs are integration surfaces. |
| Text streams | Event streams and ContextFS files should be readable and pipeable. |
| Prototype early, rebuild clumsy parts | Hook runner and ContextFS render plan are exactly this: rebuild the clumsy parts, not the whole system. |

### Design implication

Do not turn tinyagent into a hidden object graph. Keep the primary integration surfaces as text and JSONL.

## Tinygrad: small internal vocabulary

Tinygrad’s appeal is that large behavior emerges from a small set of concepts. The analogous tinyagent vocabulary should stay short:

- Event;
- State;
- Model;
- Tool;
- Policy;
- Profile;
- Context file;
- Extension.

Everything else is a composition of these.

### Design implication

A new concept must either simplify this vocabulary or live outside the core. “Plan manager,” “memory manager,” “subagent manager,” and “workflow graph” are suspicious by default.

## Robotics: layered competence and behavior trees

Robotics has long dealt with autonomous systems operating under uncertainty, partial observability, and changing environments. Two patterns are especially useful.

### Subsumption-style layering

Rodney Brooks’s subsumption architecture decomposed robot behavior into layers of increasing competence. Lower layers handle immediate constraints; higher layers add more capable behavior without replacing the lower ones.

Mapping to tinyagent:

| Robotics layer | Tinyagent layer |
| --- | --- |
| Collision avoidance | Policy/sandbox/path checks. |
| Wandering/exploration | Search/read/shell inspection. |
| Goal seeking | Profile planning and model loop. |
| Task-level behavior | Product shell / user workflow. |

Design lesson:

> Safety and basic recovery should be lower layers that cannot be bypassed by clever higher-level abstractions.

This argues for keeping policy, artifact visibility, and workspace boundary checks explicit.

### Behavior trees

Behavior trees are popular in robotics and games because they are modular, reactive, and readable. A behavior tree node either succeeds, fails, or keeps running. This maps well to tool dispatch and finish gates, but tinyagent should not import a full behavior-tree runtime.

Useful mapping:

| Behavior tree concept | Tinyagent mapping |
| --- | --- |
| Sequence node | model call -> tool calls -> context refresh -> next loop. |
| Selector node | choose policy outcome: allow, approve, deny, block. |
| Decorator node | progress guard, sandbox guard, finish gate. |
| Tick | one loop iteration or tool dispatch. |
| Blackboard | RunState plus ContextFS files. |

Design lesson:

> Use behavior-tree thinking for local clarity, not as a new framework.

The `_dispatch_tool_call` method can be cleaned by making its decision pipeline read like a sequence of guards and transforms. That does not require a behavior-tree library.

## ROS: topics, services, and actions

ROS distinguishes between topics, services, and actions. Topics are streaming messages. Services are quick request/response. Actions are long-running goals with feedback and cancellation.

Mapping to tinyagent:

| ROS primitive | Tinyagent equivalent |
| --- | --- |
| Topic | Event stream / SSE / JSONL live sink. |
| Service | Read artifact, list runs, resolve config, quick tool catalogue lookup. |
| Action | Agent run, tool execution, model call, approval wait. |

Design lesson:

> Long-running operations need progress, cancellation, and final result semantics.

This supports the SDK refactor. `Agent.run()` should not be just an async generator. It should return or expose a run handle with events, cancellation, approvals, and result retrieval.

## Control theory: feedback loops and observability

A control system observes state, computes an action, applies the action, measures the result, and corrects error. Agent harnesses do the same:

1. Build context.
2. Model proposes action.
3. Policy and executor mediate action.
4. Events and observations capture result.
5. ContextFS and profile feed result back into the next iteration.

### Design implication

Tinyagent should treat event metrics as feedback signals, not logs after the fact. Finish gates, progress guards, evals, and context planning are control components.

The main control failure modes are:

| Failure mode | Tinyagent symptom | Countermeasure |
| --- | --- | --- |
| Poor observability | Model repeats commands or misses failures | Better observations, ContextFS, recent tool selection. |
| Overloaded controller | Prompt bloat, too many tools | `tiny-pi`, dynamic context, profile variants. |
| Weak actuator limits | Unsafe shell / file writes | Policy, sandbox, approval, path checks. |
| No feedback on performance | Harness changes feel good but regress | Evals, event invariants, solve/context metrics. |
| Integral windup analogue | Agent accumulates stale context and overreacts | Compaction, ContextFS discovery, checkpointing. |

## Physics: least action and invariants

Physics often explains complex behavior through compact principles and conserved quantities. This is useful as a design metaphor.

### Least action

Prefer the design that achieves the required behavior with the fewest conceptual moves. For tinyagent, that means:

- use files before databases;
- use events before graph runtimes;
- use profiles before complex conditional prompt logic;
- use extensions before core features;
- use evals before opinions.

### Invariants

Good systems have conserved truths. Tinyagent should define invariants that every refactor preserves:

- every run has ordered event IDs;
- every durable event is JSON-safe;
- every hidden artifact route rejects hidden artifacts;
- every tool result has a transcript record;
- every long output has an artifact or explicit truncation;
- every workspace mutation emits delta evidence when possible;
- every approval wait closes its step;
- every final answer after edits has diff/inspection and verification evidence or an explicit limitation.

These invariants are more important than module names.

## Product design: progressive disclosure

Good product systems reveal complexity only when needed. Cursor’s dynamic context and Pi’s resource discovery are both forms of progressive disclosure.

### Mapping to tinyagent

- Static prompt: minimal orientation.
- ContextFS index: discoverable map.
- `context_search`: discover refs.
- `context_read`: read details.
- Skills: list descriptions, then load full instructions.
- MCP: search catalogue, load schema, call tool.
- Artifacts: list public outputs, hide internals by default.

Design lesson:

> Progressive disclosure should be the default for context, tools, and product UI.

## Summary of cross-domain patterns

| Domain | Pattern | Tinyagent application |
| --- | --- | --- |
| Unix | Text interfaces and composition | JSONL events, markdown ContextFS, CLI/SDK/RPC. |
| tinygrad | Small internal vocabulary | Keep primitives few and inspectable. |
| Robotics | Layered safety and competence | Policy/sandbox below model/profile behavior. |
| Behavior trees | Guarded execution sequences | Tool dispatch pipeline without full graph runtime. |
| ROS | Long-running actions with feedback | Cancellable SDK run handles. |
| Control theory | Feedback and correction | Observations, finish gates, progress guards, evals. |
| Physics | Invariants and least action | Event/artifact/path invariants; no excess abstractions. |
| Product design | Progressive disclosure | Dynamic context and lazy tools. |

## Resulting design rule

Tinyagent should be built like a small robot controller, not like a SaaS platform:

- low-level safety is always active;
- high-level behavior is pluggable;
- state is observable;
- actions are cancellable;
- long-running goals produce feedback;
- competence grows by adding layers, not by mutating the base layer.
