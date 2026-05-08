# Tinyagent Design Philosophy

## North star

Tinyagent should be slim, minimal, expressive, and traceable. The desired feel is closer to tinygrad than to a traditional enterprise agent platform: small primitives, explicit data, few layers, direct code, and no abstraction that cannot justify its own weight.

The ideal tinyagent core is not the product. It is the harness kernel. Product shells can be elaborate; the kernel should be boring.

## The tinygrad analogy

Tinygrad’s design appeal is not that it lacks capability. It is that capability emerges from a small, inspectable set of internal concepts. The lesson for tinyagent is not “make every file tiny.” It is:

- minimize the number of concepts a reader must hold;
- keep dataflow visible;
- prefer simple composable primitives over feature objects;
- make extension points explicit and narrow;
- force complicated behavior to leave traces.

For tinyagent, the conceptual core should be:

| Primitive | Responsibility | Must stay small? | Why |
| --- | --- | ---: | --- |
| `RunState` | Ordered mutable run state and event emission | Yes | This is the trace root. |
| `Event` | Durable or ephemeral fact about the run | Yes | This is the API of reality. |
| `ModelProvider` | Produce model response or stream deltas | Yes | Providers vary; contract must not. |
| `Tool` | One callable external capability | Yes | Tools are extension atoms. |
| `Policy` | Decide whether a tool may run | Yes | Safety boundary. |
| `Profile` | Choose prompt, tools, compaction, finish behavior | Medium | Profiles encode workflow personality. |
| `ContextFS` | Write model-readable recovery files | Medium | Powerful but can bloat. |
| `Extension` | Add hooks/tools/skills/context sources | Yes | Extensibility boundary. |

The core should not contain product features. It should expose primitives that make product features easy to build outside the core.

## Pi-aligned principles

Pi’s public docs and design essay emphasize a minimal terminal harness, customizable resources, four default tools, optional discovery, JSON/RPC and SDK modes, and “primitives, not features.” That is the strongest external anchor for tinyagent’s next direction.

Tinyagent should internalize these principles:

### 1. Primitives over features

A todo system is a feature. A writable markdown file plus an optional tool is a primitive. A plan mode is a feature. A profile plus finish gate plus file-backed note is a primitive. MCP auto-loading is a feature. A context source and lazy load tool are primitives.

The default should expose primitives. Features can be packages.

### 2. Files over hidden memory

If the agent needs persistent working state, it should usually write a file. Files can be inspected by humans, diffed, copied, replayed, forked, and indexed. Hidden in-memory state is acceptable only for control metadata or temporary execution.

This does not mean every file should be prompt-injected. The model should discover files dynamically.

### 3. Minimal default tools

The full agent can know many tools, but the default profile should not expose many tools. Too many tools increase prompt size, planning entropy, and model-specific errors.

Default `tiny-pi` tool surface:

- read file;
- edit/write file;
- shell;
- optional grep/find/ls if they are genuinely cheaper than shell.

Everything else is an extension or alternate profile.

### 4. Extension by addition, not mutation

Extensions should add hooks, tools, skills, and context sources without forcing core changes. The core should not know about every optional subsystem.

`Kernel` should receive loaded resources. It should not discover everything itself.

### 5. Explicit traces are not optional

Minimalism must not mean no trace. A tiny agent without a durable event log is hard to debug, evaluate, and trust. Tinyagent’s event model is one of its strongest assets and should be preserved.

The rule should be:

> Every irreversible or externally meaningful action emits an event. Every large payload becomes an artifact. Every artifact exposure path is policy-aware.

### 6. Safety as an execution envelope

Policy is a classifier. Sandbox is an enforcement boundary. Approval is an interaction pattern. They should be separate but coordinated.

Tinyagent can remain lean by defining an `ExecutionEnvelope` and keeping enforcement pluggable. Do not bury safety decisions inside tool code when they belong in policy or executor boundaries.

### 7. Model-specific profiles beat universal prompts

Different model families prefer different editing styles, tool naming, and context shapes. Cursor’s harness work shows that per-model tool and prompt shaping matters. Tinyagent should make that first-class through profiles, not through one giant prompt.

### 8. Evals guard taste

A minimal design can regress invisibly: fewer tools might reduce solve rate; more context might improve solve rate but create bloat; safety fixes might block too much. The only way to keep taste honest is to encode design goals as metrics.

Recommended metrics:

- solve rate;
- edit success rate;
- verification-after-edit rate;
- context token estimate;
- static prompt/tool token count;
- tool-call count;
- repeated command count;
- policy denial count;
- finish-gate blocks;
- hidden artifact exposure tests;
- event sequence invariants.

## Tinyagent design commandments

1. A new abstraction must delete more complexity than it adds.
2. A new feature must either be a profile, extension, or product-shell concern unless it is a true kernel primitive.
3. If a feature needs memory, first ask whether a file is enough.
4. If a feature needs orchestration, first ask whether an event stream and simple state file are enough.
5. Do not prompt-inject what the model can discover by reading.
6. Do not hide safety in convenience defaults.
7. Do not make the common local coding path pay for MCP, LSP, memory, subagents, or cloud features.
8. Preserve replayability before adding sophistication.
9. Prefer tests around event output over tests around private helper structure.
10. Keep the default mental model smaller than the implementation.

## Lean scorecard

Before merging a change, ask:

| Question | Pass condition |
| --- | --- |
| Can the concept be explained in one sentence? | Yes. |
| Does it reduce `Kernel` or ContextFS burden? | Yes, or it belongs outside core. |
| Is event output preserved or intentionally versioned? | Yes. |
| Can a user inspect the resulting state as files/events? | Yes. |
| Does it improve a metric or unlock an extension seam? | Yes. |
| Does it make `tiny-pi` heavier? | No, unless explicitly configured. |
| Can it be removed without breaking the core? | Usually yes for extensions/features. |

## The philosophical split

There should be two explicit modes of thinking about the repo:

### Kernel mode

The kernel answers: what is the smallest mechanism that can run, trace, and safely mediate a model/tool loop?

Kernel code should be sparse, direct, and test-heavy.

### Product mode

Product shells answer: what interfaces make the kernel useful to humans and systems?

Product code can include HTTP routes, UI metadata, sessions, workspace registries, cloud adapters, multi-agent views, and convenience flows.

The mistake to avoid is letting product concerns leak into the kernel.
