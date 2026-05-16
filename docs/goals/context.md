
The broad pattern is this: the strongest agent systems are moving away from “put everything into the prompt” and toward “make context discoverable.” The model gets a compact working set, then pulls files, logs, docs, tools, skills, memories, or subagent results only when needed.

A few terms first.

“Context” is the finite token window the model can see at inference time. It usually contains system instructions, developer instructions, user messages, tool schemas, previous assistant messages, retrieved files, and tool outputs. The important point is that tool outputs count too; a long test log, grep result, or API response can poison the working context just as much as a long conversation.

“Tool use” is the loop where the model chooses an external action, the harness executes it, and the result is returned as an observation. A shell command, code search, patch application, browser fetch, MCP call, database query, or subagent invocation are all tools. The model is not just “answering”; it is operating a small external computer through a constrained interface.

“Large output” has two meanings. First, a tool can produce a large observation, such as 10,000 lines of logs. Second, the agent can need to produce a large artifact, such as a full implementation, report, generated file, or multi-file patch. Mature harnesses avoid dumping either directly into chat. They use files, summaries, handles, diffs, checkpoints, and retrieval.

The main strategies across the systems you named are these.

Cursor is probably the clearest public example of “dynamic context discovery.” Their harness gives the model fewer static details up front and lets it fetch context as it works. Cursor writes long tool, MCP, and shell outputs to files, then gives the agent a handle so it can read, tail, or search the output later. It also treats chat history and terminal sessions as searchable files, syncs MCP tool descriptions into a folder rather than loading all tool details into the prompt, and uses codebase indexing for large-repo recall. Cursor has also said it tunes the harness per model, because different model families behave better with different edit formats and tool scaffolds.

Hermes leans into persistent agent memory, skills, compression, and subagents. Its docs describe AGENTS.md-style recurring instructions, lazily discovered subdirectory instructions, /compress for summarizing history, bounded memory that consolidates when full, skill files for repeatable procedures, and delegated tasks where subagents have their own context and return only summaries. It also emphasizes using code execution to batch operations instead of making many small terminal calls, which is a tool-use optimization as much as a speed optimization.

Cognition/Devin appears to treat context less as “one prompt” and more as an operational workspace. Public material describes repo indexing, Ask Devin for codebase Q&A, DeepWiki-style auto-generated repo documentation, playbooks for repeated workflows, MCP integrations for logs and external systems, session insights after completed runs, and breaking large work into smaller isolated tasks. Devin also has both local and cloud execution modes, which matters because long-running work often needs a persistent environment, not just a long context window.

xAI’s public story is more model/API-centric than harness-centric. Grok Code Fast is described as trained for fast agentic coding loops and common tools like terminal, grep, and file editing. Grok 4.1 Fast is described with a 2M-token context window, server-side tools such as web search and code execution, and reinforcement learning across tool-rich simulated environments. So the strategy there is partly “make the model itself better at tool use and long context,” plus prompt caching. Public details are thinner on the surrounding coding-agent harness compared with Cursor, Claude Code, Amp, or Droid.

Factory Droid emphasizes harness design explicitly. Their docs describe settings for models, tools, permissions, AGENTS.md, skills, MCP services, custom Droids, hooks, plugins, IDE/Slack/Linear integration, and org knowledge. In their Terminal-Bench writeup, they call out hierarchical prompting, model-specific optimizations, minimalist tool design, system notifications, session bootstrapping with salient environment info, short default tool timeouts, plan-progress reminders, and a controlled background execution primitive for long-running processes. That is a very harness-heavy approach: constrain tools, shape context, and manage execution state carefully.

Amp uses lazy-loaded skills, MCP containment, and subagents. Its manual says a skill’s name and description are visible, but the rest loads on demand. It recommends putting MCP servers inside skills so their tools remain hidden until relevant, and warns that too many tools degrade performance. Amp’s Task tool creates subagents with their own context, useful when the main thread should not be polluted by exploration or large intermediate output. It also has specialized helpers like Oracle and Librarian for second opinions and cross-repo research.

Codex uses AGENTS.md and skills as progressive-disclosure mechanisms. The official AGENTS.md guide says Codex reads global and project-specific instruction files, merges them from root down to the working directory, and caps combined project docs by default. Codex Agent Skills similarly use progressive disclosure: the model initially sees skill names, descriptions, and paths, while full skill content is loaded only when selected; the initial skill list is also budgeted to avoid overwhelming context.

Claude/Claude Code combines several of these ideas. Claude Code exposes file, shell, web, git, MCP, memory, skill, and subagent tools, and its custom subagents preserve the main conversation context by keeping exploration or implementation details outside the main thread. Anthropic also documents context compaction, where old conversation blocks are summarized near the context limit, and Tool Search, where the model discovers only the tools it needs instead of seeing every tool definition. Anthropic’s “programmatic tool calling” idea is also important: instead of having the model manually call many tools and ingest every result, it writes code that calls tools, filters intermediate results, and returns only the useful information.

So the shared strategies are fairly clear.

First, static context is minimized. The harness does not preload the entire repo, all docs, all memories, all tool descriptions, and all logs. It starts with a compact task state and lets the model retrieve what it needs.

Second, large observations are externalized. Instead of returning a huge shell output to the model, the harness stores it as an artifact and returns a short summary plus a path or handle. The model can then call read, tail, grep, or search on that artifact.

Third, tools are progressively disclosed. A small always-available tool set is better than exposing 80 tools with long schemas. Skills, MCP servers, and specialized tools are loaded only when relevant.

Fourth, context is compressed but made recoverable. Summaries are useful, but they are lossy. Stronger systems keep underlying transcripts, logs, or artifacts searchable so the agent can recover details the summary omitted.

Fifth, subagents isolate context. Exploration, code review, debugging, log analysis, or research can happen in separate contexts. The parent agent receives only a summary, artifact references, and possibly a proposed patch.

Sixth, model-specific harnessing matters. A tool format that works well for one model can be awkward for another. Some models prefer patch-based editing, some prefer search/replace, some need stricter JSON, some need fewer choices, and some are more sensitive to prompt-cache invalidation.

Seventh, large final output is usually turned into durable artifacts. For code, the ideal output is not a huge message; it is a patch, commit, PR, or changed files. For analysis, it may be a report file. For logs, it may be a summarized diagnostic with links to raw artifacts.

For the current harness we have discussed, the strategy is more minimal and auditable.

It has a microkernel shape: a core loop that builds context, calls the model, dispatches tools, records events, compacts state, and checks finishing conditions. The context is layered: system/profile instructions, environment information, project/task instructions, recent interaction, and recent tool previews. It has basic shell and patch tools, deterministic compaction, JSONL traces or artifacts, approval/policy handling, and a comparatively small dependency footprint.

That is a good foundation because it is inspectable. The tradeoff is that it is not yet as context-adaptive as Cursor, Claude Code, Amp, or Droid. The missing pieces are mostly not “bigger context.” They are better context logistics.

The first future upgrade should be an observation store. Every tool call should return a structured observation, not just text. Something like:

Observation
- short_summary: what happened
- status: success / failure / partial
- artifact_refs: paths to full stdout, stderr, generated files, screenshots, traces
- important_spans: line ranges or snippets worth seeing immediately
- suggested_next_reads: files or commands likely relevant next
- metadata: command, cwd, exit code, duration, token estimate

The model should see the summary and a few important spans. Full output should live outside the prompt. Then the harness needs tools like read_artifact, tail_artifact, grep_artifact, open_span, and summarize_artifact. This would adopt Cursor’s “long outputs as files” pattern and Anthropic’s “filter intermediate results before putting them into context” pattern.

The second upgrade should be a context budget controller. The harness should maintain a ledger of what is consuming tokens: instructions, tool schemas, current plan, file snippets, history, artifacts, memory, and summaries. Then it should assemble context by priority. Highest priority would be current user request, active plan, open errors, modified files, and direct dependencies. Lower priority would be old conversation turns, stale logs, unrelated repo summaries, and unused tool descriptions.

The third upgrade should be progressive tool disclosure. Keep a tiny base tool set: shell, patch, read file, search files, maybe run tests. Everything else should be behind skills or tool packs. For example: “Python debugging,” “frontend browser testing,” “GitHub PR review,” “database inspection,” “paper summarization,” or “MCP Linear workflow.” The initial context should contain only names and short descriptions. Full instructions and tools load when selected.

The fourth upgrade should be project memory with clear separation between facts and procedures. Facts are things like “this repo uses uv,” “tests live under tests/,” or “the backend service must be run with profile X.” Procedures are repeatable workflows like “how to run integration tests,” “how to release,” or “how to debug flaky Playwright tests.” Facts can be compact. Procedures should live as skills or runbooks.

The fifth upgrade should be recoverable compaction. A compacted state should contain the current goal, constraints, decisions made, files touched, tests run, known failures, artifact handles, and unresolved questions. It should not try to preserve every detail. But the raw transcript and tool outputs should remain searchable, so the model can recover from a bad or lossy summary.

The sixth upgrade should be subagents, but only for cleanly separable tasks. Good subagent roles are “explore the repo,” “find all callers,” “review this patch,” “debug this failing test,” “summarize these logs,” and “compare implementation options.” Bad subagent use is letting multiple agents edit the same files without coordination. The parent harness should require each subagent to return a structured result: claim, evidence, artifact refs, changed files if any, confidence, and remaining risks.

The seventh upgrade should be model-specific adapters. The kernel should not assume one universal editing or tool-calling style. It should support adapters for patch editing, string replacement, JSON-only tool calls, shell-first workflows, or code-execution-first workflows. The same abstract tool can have different descriptions and scaffolding depending on the model.

The eighth upgrade should be evals and harness telemetry. Useful metrics are not just “task success.” Track tool error rate, repeated failed commands, token cost per accepted edit, compaction loss, unnecessary file reads, patch rejection rate, time spent in tools, number of context refreshes, and whether final edits survive review. Cursor publicly mentions measuring harness changes with offline benchmarks and online metrics such as latency, token efficiency, tool call count, cache hit rate, and edit keep rate; that general evaluation mindset is worth copying.

The ninth upgrade should be a repo intelligence layer. File search is useful, but code agents benefit from symbols, call graphs, dependency graphs, git history, test ownership, architectural summaries, and generated module maps. Recent research systems point in the same direction: use structured code graphs and hierarchical repo representations so the model can progressively inspect relevant parts instead of reading the repo linearly.

A plausible future architecture would look like this:

Agent Kernel
  -> Context Assembler
  -> Tool Router
  -> Observation Store
  -> Artifact Store
  -> Compactor
  -> Retrieval / Code Index
  -> Skill Loader
  -> Subagent Manager
  -> Policy / Sandbox
  -> Evaluator / Telemetry

The kernel stays small. The intelligence moves into the context assembler, observation store, retrieval layer, and evaluators.

The key design principle I would use is:

The model should see the smallest sufficient working set,
plus reliable handles to recover everything else.

That is the core difference between a toy harness and a serious one. A toy harness feeds the model a transcript. A stronger harness manages an external memory hierarchy: prompt, summary, artifacts, files, tools, indexes, skills, subagents, and traces.