# Streaming + Harness Baseline Discovery

Status: discovery artifact
Date: 2026-04-27
Scope: research only, no runtime implementation

This document compares Tinyagent's current harness shape against streaming,
tracing, tool-loop, and eval behavior in existing agent systems. It does not
prescribe a code patch. The goal is to ask the right questions before adding
streaming.

## Tinyagent Current State

Tinyagent currently has no streaming runtime path.

Local evidence:

- `agentd/models.py`: `ModelProvider.complete(...) -> ModelResponse`; OpenAI-compatible provider calls `/chat/completions` once and parses one full response.
- `agentd/kernel.py`: the kernel writes `ModelRequest`, calls `model.complete(...)`, then writes one final `ModelResponse` artifact.
- `agentd/output.py`: context, logical request, HTTP request, response, command output, final output, metrics, and final diff are persisted as artifacts.
- `agentd/context.py`: context checkpoints are deterministic local summaries.
- `agentd/replay.py`: replay renders an event timeline and does not execute side effects.

Implication: Tinyagent is strong on small-kernel trace discipline, but behind
mature harnesses on live event streaming, partial tool-call assembly, and
client-facing stream protocols.

## Source Index

Unless otherwise noted, sources were accessed on 2026-04-27.

| Ref | System | Source |
| --- | --- | --- |
| S1 | OpenAI API streaming | <https://platform.openai.com/docs/guides/streaming-responses> |
| S2 | OpenAI Responses streaming reference | <https://platform.openai.com/docs/api-reference/responses-streaming/response/function_call_arguments/delta> |
| S3 | OpenAI Agents SDK Python streaming | <https://openai.github.io/openai-agents-python/streaming/> |
| S4 | OpenAI Agents SDK repo guidance | <https://github.com/openai/openai-agents-python/blob/main/AGENTS.md> |
| S5 | OpenAI Agents SDK JS streaming | <https://openai.github.io/openai-agents-js/guides/streaming/> |
| S6 | Codex harness article and protocol | <https://openai.com/index/unlocking-the-codex-harness/>; <https://github.com/openai/codex/blob/main/codex-rs/docs/protocol_v1.md> |
| S7 | OpenHands | <https://docs.openhands.dev/sdk/arch/events>; <https://github.com/OpenHands/OpenHands> |
| S8 | SWE-agent | <https://github.com/swe-agent/swe-agent> |
| S9 | Aider | <https://github.com/aider-ai/aider> |
| S10 | Goose | <https://goose-docs.ai/>; <https://goose-docs.ai/docs/getting-started/using-extensions/> |
| S11 | OpenCode | <https://opencode.ai/>; <https://github.com/opencode-ai/opencode> |
| S12 | Continue | <https://docs.continue.dev/ide-extensions/agent/how-it-works> |
| S13 | Pi | <https://www.pi-gui.com/>; <https://github.com/rytswd/pi-agent-extensions>; <https://eliteai.tools/agent-skills/pi-extension-builder> |
| S14 | Hermes Agent | <https://hermes-agent.nousresearch.com/docs/user-guide/features/memory/>; <https://hermes-agent.ai/blog/hermes-agent-memory-system> |
| S15 | Gemini CLI | <https://github.com/google-gemini/gemini-cli> |
| S16 | Claude/Claude Code | <https://platform.claude.com/docs/en/api/streaming>; <https://code.claude.com/docs/en/agent-sdk/streaming-output> |
| S17 | Cursor | <https://docs.cursor.com/en/agent/terminal>; <https://docs.cursor.com/en/cli> |
| S18 | Windsurf | <https://docs.windsurf.com/windsurf/cascade/modes>; <https://docs.windsurf.com/windsurf/cascade/mcp> |
| S19 | LangGraph | <https://docs.langchain.com/langgraph-platform/streaming> |
| S20 | AutoGen/Magentic-One | <https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/agents.html>; <https://arxiv.org/abs/2411.04468> |
| S21 | CrewAI | <https://docs.crewai.com/en/learn/streaming-crew-execution/index.html>; <https://docs.crewai.com/en/enterprise/features/webhook-streaming> |
| S22 | Pydantic AI | <https://pydantic.dev/docs/ai/core-concepts/agent/>; <https://ai.pydantic.dev/ui/overview/> |
| S23 | smolagents | <https://huggingface.co/docs/smolagents/reference/agents> |
| S24 | Vercel AI SDK | <https://ai-sdk.dev/docs> |
| S25 | LiteLLM | <https://docs.litellm.ai/> |
| S26 | Open Interpreter | <https://docs.openinterpreter.com/guides/streaming-response> |
| S27 | Cline | <https://github.com/cline/cline>; <https://docs.cline.bot/tools-reference/all-cline-tools> |
| S28 | Roo Code | <https://github.com/RooCodeInc/Roo-Code>; <https://roocode.com/> |
| S29 | GitHub Copilot coding agent | <https://docs.github.com/en/copilot/concepts/coding-agent/about-copilot-coding-agent> |

## Baseline Matrix

Legend:

- Better: Tinyagent is already meaningfully ahead on this axis.
- On par: Tinyagent has comparable minimum behavior.
- Behind: Tinyagent lacks the capability or has only a thinner version.
- Not found: no public primary evidence found in this pass.

| System | Streaming surface and protocol | Tool-call assembly and live tool surface | Durability, completion, failures | General harness features | Tinyagent comparison |
| --- | --- | --- | --- | --- | --- |
| Tinyagent | No streaming path. Synchronous `complete(...)` only. Source: local `agentd/models.py`, `agentd/kernel.py`. | Tool calls arrive already parsed in final `ModelResponse`; no partial tool-call buffering. Source: local `agentd/models.py`. | Events/artifacts are durable; replay is read-only; no streaming disconnect/cancel path. Source: local `agentd/output.py`, `agentd/replay.py`. | Shell, apply_patch, hidden repo tools, context checkpoints, event log, artifacts. Source: local files above. | Baseline. Strong trace discipline, behind on live streaming. |
| OpenAI API Responses/Chat | SSE streaming; Responses API exposes semantic events including text and function-call argument deltas. Sources: S1, S2. | Function-call arguments can stream as deltas and must be assembled by client code. Source: S2. | Completion/error semantics are provider stream events; client owns persistence and failure policy. Source: S1. | Provider API, not a harness. Source: S1. | Behind on raw/semantic streaming; ahead only on local replay because OpenAI API does not provide harness replay. |
| OpenAI Agents SDK Python | Async stream object; raw model events plus higher-level run-item and agent-updated events. Source: S3. | Tool calls/results appear as run item stream events after higher-level assembly. Source: S3. | Stream is complete only after consuming the result stream; SDK docs distinguish raw and run-item events. Source: S3. | Tools, handoffs, tracing, guardrails, sessions. Source: S3. | Behind on stream taxonomy and run item events; Tinyagent is smaller and easier to audit. |
| OpenAI Agents SDK JS | Async iterable stream; can convert to text stream and await completion. Source: S5. | Tool and run events are exposed through SDK stream items. Source: S5. | Stream completion is explicit; non-streaming and streaming parity is an SDK design concern. Sources: S4, S5. | Tools, handoffs, tracing, guardrails. Source: S5. | Behind on public streaming API; on par with the principle that streaming/non-streaming should stay aligned. |
| Codex CLI/app server | Protocol-oriented agent harness; public protocol docs describe request/response and event surfaces. Sources: S6. | Tool call details are part of the harness protocol, but exact partial assembly policy requires source inspection. Source: S6. | Codex article emphasizes compacted context, event handling, and harness protocol. Source: S6. | Local coding agent, shell/file tools, policies, context compaction. Source: S6. | Behind on production-hardened protocol and app-server interface; on par philosophically with small kernel plus profile/tool loop. |
| OpenHands | Event architecture is first-class; events represent observations/actions in the runtime. Sources: S7. | Tool/action events are normalized in the event stream; partial provider chunk policy not found in public docs. Source: S7. | Durable event stream and runtime state are core architecture. Source: S7. | Sandbox/runtime, file and terminal actions, web, agent loop, UI. Source: S7. | Behind on eventstream maturity and sandbox breadth; Tinyagent is smaller and has simpler artifacts. |
| SWE-agent | Repo focuses on software engineering agent loops and agent-computer interface. Source: S8. | Tool/action execution is central; partial streaming assembly detail not found in public docs reviewed. Source: S8. | Logging/evals are core to the benchmark-oriented workflow; exact replay semantics not found in this pass. Source: S8. | SWE-bench style tasks, shell/file actions, trajectories/evals. Source: S8. | Behind on eval maturity; Tinyagent has comparable local shell/edit primitives at smaller scope. |
| Aider | CLI streams model output to terminal in normal chat flow. Source: S9. | Uses edit formats and repo-aware workflows; partial tool-call JSON is less central because Aider historically uses text/edit protocols. Source: S9. | Chat history and git diffs are central; raw chunk replay not found in public docs reviewed. Source: S9. | Repo map, git integration, lint/test commands, many providers. Source: S9. | Behind on provider breadth and repo-map maturity; Tinyagent is stronger on explicit event/artifact taxonomy. |
| Goose | Agent CLI/app with extensions and MCP-oriented tool use. Sources: S10. | Tools/extensions are visible to the agent; partial streaming assembly details not found in docs reviewed. Source: S10. | Session/log durability details not fully found in this pass. Source: S10. | Extensions, MCP, computer-use orientation, CLI/app modes. Source: S10. | Behind on extension and MCP surface; Tinyagent is more minimal and trace-explicit. |
| OpenCode | Terminal coding agent with TUI/server orientation; docs/source indicate interactive live operation. Source: S11. | Tool and file edits are core; exact partial tool-call streaming policy not found in docs reviewed. Source: S11. | Session durability and replay details not found in this pass. Source: S11. | Multi-provider coding agent, terminal UX, project context. Source: S11. | Behind on terminal UX and live interaction; Tinyagent has clearer artifact trace discipline. |
| Continue | Agent Mode docs describe tool decisions, model actions, IDE execution, and MCP/configurable tools. Source: S12. | Agent chooses tools and receives observations inside IDE workflow; partial streaming assembly not found in docs reviewed. Source: S12. | IDE state and chat history exist; durable replay artifact model not found. Source: S12. | IDE-integrated edits, terminal, MCP, config, model support. Source: S12. | Behind on IDE integration; Tinyagent stronger on portable event/artifact traces. |
| Pi | Public Pi GUI and extension examples emphasize local-first GUI and TypeScript extension packages. Sources: S13. | Extension examples show custom tools/commands; partial stream assembly details not found. Sources: S13. | Durable replay/trace details not found in public primary docs reviewed. Source: S13. | Extension model, GUI, local agent flow. Source: S13. | Behind on extension UX; Tinyagent should copy the distinction between small core and extensible profile/resources. |
| Hermes Agent | Public docs emphasize persistent memory and generated/managed knowledge rather than streaming. Sources: S14. | Tool-call streaming details not found. Source: S14. | Memory persistence is a major feature; trace/replay semantics not found in public docs reviewed. Sources: S14. | Memory, user preferences, generated knowledge/skills. Sources: S14. | Behind on memory; memory is intentionally out of current Tinyagent scope. Not a primary streaming baseline. |
| Gemini CLI | Open-source CLI coding agent for Gemini; terminal-agent flow. Source: S15. | Tool use is core; partial tool-call stream assembly requires source inspection beyond this pass. Source: S15. | Session/checkpoint/replay semantics not found in docs reviewed. Source: S15. | CLI coding, tools, project context, provider-specific integration. Source: S15. | Behind on Google provider integration and CLI maturity; Tinyagent clearer on provider-neutral artifacts. |
| Claude API/Claude Code SDK | Claude API supports SSE events; Claude Code SDK documents streaming output modes. Sources: S16. | Claude stream has content/tool event shapes at API level; Claude Code SDK exposes message streaming. Sources: S16. | Stream completion and errors are API events; SDK output can be consumed incrementally. Sources: S16. | Claude Code provides an agent SDK/CLI surface; detailed internal replay not found. Source: S16. | Behind on SDK stream surface; Tinyagent can be on par only if it separates raw provider chunks from normalized harness events. |
| Cursor | Agent terminal docs describe command allowlists/denylists and terminal behavior; CLI docs show agent invocation. Sources: S17. | IDE agent can run terminal commands; partial tool-call assembly not public. Source: S17. | Trace/replay internals not found in public docs. Source: S17. | IDE agent, terminal command policy, background/CLI flows. Source: S17. | Behind on IDE/user-facing UX; Tinyagent stronger on inspectable local trace files. |
| Windsurf | Cascade docs describe modes and MCP/tool integration. Sources: S18. | Agent/tool behavior is documented at mode/MCP level; partial streaming internals not public. Source: S18. | Trace/replay internals not found. Source: S18. | IDE agent modes, terminal/tool actions, MCP. Source: S18. | Behind on IDE and MCP UX; Tinyagent should stay explicit rather than copy opaque IDE behavior. |
| LangGraph | Platform docs provide stream modes for values, updates, messages, custom data, and debug. Source: S19. | Tool/graph node updates can be streamed by mode; graph state mediates assembly. Source: S19. | Checkpointing, durable state, and streaming modes are central. Source: S19. | Graph runtime, persistence, human-in-loop, deployment. Source: S19. | Behind on durable streaming/checkpoint framework; Tinyagent is intentionally much smaller. |
| AutoGen/Magentic-One | AutoGen has `run_stream`/model client streaming; Magentic-One describes multi-agent orchestration. Sources: S20. | Tool call summaries/events are surfaced in agent chat; exact partial JSON policy depends on model client. Source: S20. | Logs/teams/termination are framework concepts; replay artifact parity not found in this pass. Source: S20. | Multi-agent orchestration, tools, termination conditions, teams. Source: S20. | Behind on multi-agent streaming; Tinyagent should avoid importing framework complexity before traces demand it. |
| CrewAI | Docs describe streaming crew execution and webhook streaming. Sources: S21. | Agent/task progress can stream; partial provider tool-call assembly not found. Source: S21. | Enterprise webhook streaming gives external durability path; local replay semantics not found. Sources: S21. | Crews, tasks, flows, webhooks, enterprise features. Source: S21. | Behind on webhook/event delivery; Tinyagent stronger for local trace files. |
| Pydantic AI | Agent docs expose streaming run APIs; UI docs define event-stream integration. Sources: S22. | Typed events and tool approval/use can flow to UI layer. Sources: S22. | Streamed run and UI event stream are explicit; replay artifact model not found. Sources: S22. | Typed agents, validation, tools, UI protocol. Source: S22. | Behind on typed event API and UI protocol; Tinyagent can copy typed normalization without adopting framework scope. |
| smolagents | Agent API exposes step-by-step execution concepts and streaming-related parameters. Source: S23. | Tool calls are part of agent steps; exact raw chunk retention not found. Source: S23. | Replay/artifact discipline not found. Source: S23. | Minimal agents, code agents, tools, managed agents. Source: S23. | On par philosophically on minimalism; behind if Tinyagent needs step streaming. |
| Vercel AI SDK | Data stream/UI message protocol and streaming helpers are core. Source: S24. | Tool calls/results can be streamed to UI clients with structured parts. Source: S24. | Client/server stream protocol is explicit; local agent replay is not the goal. Source: S24. | Web app streaming, providers, tool calling, UI state. Source: S24. | Behind on client streaming protocol; Tinyagent should copy structured parts only if building a UI. |
| LiteLLM | Provider gateway supports streaming across many model APIs. Source: S25. | Tool-call streaming is mostly pass-through/normalization; harness tool execution is out of scope. Source: S25. | Gateway logging/cost/routing; agent replay not the focus. Source: S25. | Provider abstraction, proxy, spend/logging, many models. Source: S25. | Behind on provider breadth; Tinyagent should not become a gateway. |
| Open Interpreter | Streaming response guide exposes incremental messages while code/interpreter actions run. Source: S26. | Code execution/tool output is central; exact partial tool-call buffering not found. Source: S26. | Conversation/session persistence exists, but trace artifact parity not found. Source: S26. | Local code execution, interpreter loop, terminal-like use. Source: S26. | Behind on live code-interpreter UX; Tinyagent stronger on explicit patch/diff artifacts. |
| Cline | VS Code agent with documented tools for file reads/writes, terminal commands, browser, and MCP. Source: S27. | Tool use is explicit in UI; partial tool-call internals not found in docs reviewed. Source: S27. | Task history/checkpoints exist in product/source, but exact replay artifact semantics not found. Source: S27. | IDE tools, terminal, browser, MCP, approvals. Source: S27. | Behind on IDE tool breadth; Tinyagent stronger on minimal auditable kernel. |
| Roo Code | VS Code agent fork/ecosystem with broad tool and mode support. Source: S28. | Tool use is explicit in IDE; partial stream internals not found in docs reviewed. Source: S28. | Durable local task/replay details not found in this pass. Source: S28. | IDE agent modes, file/terminal/browser/MCP tools. Source: S28. | Behind on IDE UX and modes; Tinyagent should avoid mode sprawl early. |
| GitHub Copilot coding agent | Cloud coding agent works on issues and PRs in GitHub-managed environment. Source: S29. | Live partial tool-call stream is not public in docs reviewed. Source: S29. | PR/commit history is durable; internal event trace not public. Source: S29. | Cloud workspace, PR flow, GitHub integration, policy boundary. Source: S29. | Behind on hosted workflow; Tinyagent can compete on local trace inspectability, not cloud orchestration yet. |

## Findings

### Top Patterns Worth Copying

1. Separate raw provider chunks from normalized harness events. OpenAI Agents SDK and Responses API make this split clear. Sources: S1, S2, S3, S5.
2. Treat streamed runs as incomplete until the stream is fully consumed and finalized. Sources: S3, S5.
3. Represent tool-call argument deltas explicitly before execution. Sources: S2, S16, S24.
4. Stream high-level run items, not only text tokens. Sources: S3, S19, S22.
5. Preserve local trace artifacts even when live UI is richer. Tinyagent already does this locally; OpenHands/LangGraph show why durable state matters. Sources: local files, S7, S19.

### Top Traps To Avoid

1. Token-only streaming. It improves perceived latency but does not answer tool, trace, or replay questions.
2. Opaque IDE-style streaming. Cursor/Windsurf/Cline/Roo are useful UX references, but public internals are not enough to copy safely. Sources: S17, S18, S27, S28.
3. Framework-sized event taxonomies. LangGraph/AutoGen/CrewAI are powerful but broader than Tinyagent's current kernel goals. Sources: S19, S20, S21.
4. Provider gateway creep. LiteLLM solves provider routing; Tinyagent should only normalize enough provider streaming to preserve harness semantics. Source: S25.
5. Running tools before streamed arguments are complete and validated. Responses API and Claude API make partial tool-call streaming visible; Tinyagent needs explicit buffering/failure rules. Sources: S2, S16.

## Core Questions Before Implementation

1. What should Tinyagent stream?
   - Recommended question framing: raw provider chunks, normalized harness events, user-visible text, tool execution events, or all four?

2. What must be replayable?
   - Recommended default: normalized harness events and final assembled model responses must be replayable; raw provider chunks should be optional artifacts for debugging.

3. How should partial tool-call JSON be handled?
   - Required decision: buffer by provider call id, validate complete JSON before policy/execution, record parse failure as a model-provider error with raw chunk artifact.

4. Should streaming and non-streaming share response assembly?
   - Recommended default: yes. Streaming should produce the same final `ModelResponse` shape as non-streaming before tool dispatch.

5. What is the minimum event taxonomy?
   - Candidate event names to evaluate later: `ModelStreamStarted`, `ModelStreamChunk`, `ModelStreamItem`, `ModelStreamFinished`, `ModelStreamFailed`.

6. What live UX matters first?
   - Recommended first live UX: model text deltas, tool-call requested, tool-call started/finished, command output artifact references, cancellation/failure.

7. What measurable claims define better?
   - Lower kernel complexity than framework agents.
   - Stronger replay than token-only CLIs.
   - Clearer raw/normalized boundary than opaque IDE agents.
   - Better failure artifacts for partial tool-call JSON.
   - Optional live smoke test gated by env credentials.

## Recommended M1.6 Milestone

Name: `M1.6 - Streaming Trace Contract`

Goal: add a minimal streaming contract only after this matrix is reviewed.

Proposed shape, not yet implementation:

- Add a provider-level stream adapter that yields raw chunks and assembles the same final `ModelResponse` used by `complete`.
- Add normalized stream events for text deltas, tool-call argument deltas, stream completion, and stream failure.
- Persist raw chunks as artifacts behind a config flag; always persist normalized stream events.
- Keep tool execution unchanged: policy and execution happen only after complete validated tool calls are assembled.
- Add deterministic fake-stream tests and one local HTTP fixture for OpenAI-compatible SSE.
- Keep live model smoke optional and gated by `TINYAGENT_MODEL_*` env.

## Acceptance Check

- Systems inspected: 29 including Tinyagent.
- Pi, Hermes Agent, and OpenCode are included.
- Claims use primary sources where found; unsupported details are marked `not found`.
- Tinyagent is compared against the same axes as external systems.
- This artifact contains patterns, traps, core questions, and a recommended M1.6 milestone.
