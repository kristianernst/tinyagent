# TinyAgent Examples

These examples are small, offline agentic flows that run against TinyAgent's real runtime with deterministic fake model responses. They are intended as stable demos for the harness: no API key, no network, and no hidden services.

The examples are shaped by recurring patterns in current agent frameworks:

- OpenAI Agents SDK examples emphasize deterministic workflows, agents-as-tools, parallel execution, LLM-as-judge, human-in-the-loop approvals, shell execution, and apply-patch editing: https://openai.github.io/openai-agents-python/examples/
- LangGraph documents human-in-the-loop workflows as an interrupt/resume pattern where execution pauses, receives human input, and continues: https://docs.langchain.com/langsmith/add-human-in-the-loop
- AutoGen describes multi-agent code-generation flows as explicit message contracts between coder, executor, and reviewer agents, including reviewer reflection loops: https://microsoft.github.io/autogen/dev/user-guide/core-user-guide/core-concepts/application-stack.html

## Run Them

```bash
uv run python examples/code_repair_flow.py
uv run python examples/research_review_flow.py
```

Both scripts accept `--workspace <path>` if you want the generated demo workspace in a predictable location.

## `code_repair_flow.py`

Shows a single coding agent loop:

1. inspect a buggy file,
2. request approval for a test command,
3. observe the failing test,
4. apply a patch,
5. rerun the approved verification command,
6. finish with concrete evidence.

This is the closest minimal showcase for TinyAgent as a coding-agent harness because it exercises policy, approvals, tool calls, patches, command artifacts, final output, and event evidence.

## `research_review_flow.py`

Shows a two-agent orchestration:

1. a researcher reads source notes and writes a short brief,
2. a reviewer consumes the brief and writes a review gate,
3. the script checks that the reviewer accepted the brief and recorded a concrete risk.

This demonstrates a handoff/reflection shape without introducing a graph framework. The handoff is just a workspace artifact and a second TinyAgent run.
