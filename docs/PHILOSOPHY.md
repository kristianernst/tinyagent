# Tinyagent Code Philosophy

Tinyagent is a small, expressive agent harness.

The core should stay readable enough that a strong LLM can understand it in one context window.

We optimize for:

- few concepts
- few files
- low ceremony
- explicit state
- replayable behavior
- strong defaults
- bounded YOLO
- benchmarked changes
- deletions over abstractions

We do not optimize for:

- framework completeness
- premature generality
- plugin machinery before plugins matter
- hidden magic
- deep inheritance trees
- code golf
- feature count

A feature is only accepted if its value exceeds its complexity cost.

A performance or capability claim needs an eval, benchmark, or trace.

A new abstraction must either remove repeated complexity or make behavior more inspectable.

The kernel must remain boring.  
The profile is where behavior lives.  
The event log is the source of truth.



Tinygrad is the right inspiration, with one caveat: do not imitate “low LoC” as code golf. Tinygrad’s own contribution guidance says low line count is a guiding light, but “no code golf”; the actual goal is reducing complexity and increasing readability. It also says speedup claims must be benchmarked, complex or large diffs are unlikely to be accepted, and features need regression tests with an explicit line-tradeoff judgment.

That philosophy maps very cleanly to Tinyagent.

The goal should not be:

```
few lines at all costs
```

The goal should be:

```
few concepts
few indirections
few hidden mechanisms
high expressiveness per line
easy model comprehension
easy human review
easy trace replay
```

A good founding rule would be:

```
Every file, class, function, and abstraction must either:
1. make the agent more capable,
2. make the harness easier to inspect,
3. make behavior more traceable,
4. make safety boundaries clearer,
5. or delete more complexity than it adds.
```

If it does not do one of those, it should probably not exist yet.



