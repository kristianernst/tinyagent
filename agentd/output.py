"""Run output writing for tinyagent."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agentd.contracts import Tool
from agentd.state import Message, ModelResponse, RunState

ARTIFACTS_DIR = "artifacts"


def write_run_outputs(state: RunState) -> None:
    state.output_dir.mkdir(parents=True, exist_ok=True)

    (state.output_dir / "events.jsonl").write_text(
        "".join(json.dumps(event.to_json_dict(), sort_keys=True) + "\n" for event in state.events),
    )
    (state.output_dir / "summary.md").write_text(_summary_text(state))
    (state.output_dir / "metrics.json").write_text(json.dumps(_metrics(state), indent=2, sort_keys=True) + "\n")
    (state.output_dir / "final.diff").write_text(state.final_diff)


def write_text_artifact(state: RunState, name: str, content: str, *, kind: str) -> str:
    relative_path = Path(ARTIFACTS_DIR) / name
    artifact_path = state.output_dir / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(content)
    state.add_event(
        "ArtifactWritten",
        {
            "kind": kind,
            "path": relative_path.as_posix(),
            "bytes": len(content.encode()),
        },
    )
    return relative_path.as_posix()


def write_json_artifact(state: RunState, name: str, data: dict[str, Any], *, kind: str) -> str:
    return write_text_artifact(
        state,
        name,
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        kind=kind,
    )


def write_model_request_artifacts(
    state: RunState,
    *,
    call_index: int,
    provider: str,
    messages: list[Message],
    tools: list[Tool],
) -> tuple[str, str]:
    context_artifact = write_text_artifact(
        state,
        f"context-{call_index:04d}.md",
        _context_markdown(messages, tools),
        kind="model_context",
    )
    request_artifact = write_json_artifact(
        state,
        f"model-request-{call_index:04d}.json",
        {
            "provider": provider,
            "messages": [_message_dict(message) for message in messages],
            "tools": [_tool_dict(tool) for tool in tools],
        },
        kind="model_request",
    )
    return context_artifact, request_artifact


def write_model_response_artifact(
    state: RunState,
    *,
    call_index: int,
    response: ModelResponse,
) -> str:
    return write_json_artifact(
        state,
        f"model-response-{call_index:04d}.json",
        {
            "content": response.content,
            "finish_reason": response.finish_reason,
            "tool_calls": [_tool_call_dict(call) for call in response.tool_calls],
            "raw": response.raw,
        },
        kind="model_response",
    )


def _summary_text(state: RunState) -> str:
    if state.failed:
        return f"# Run failed\n\n{state.failure_reason or 'Unknown failure'}\n"
    return f"# Run finished\n\n{state.summary or 'No summary produced.'}\n"


def _metrics(state: RunState) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "status": "failed" if state.failed else "finished",
        "failure_reason": state.failure_reason,
        "task": state.task,
        "workspace_root": str(state.workspace.root),
        "output_dir": str(state.output_dir),
        "turn_count": state.turn_count,
        "tool_call_count": state.tool_call_count,
        "duration_seconds": state.elapsed_seconds(),
        "budgets": asdict(state.budgets),
        "final_diff_available": bool(state.final_diff),
    }


def _context_markdown(messages: list[Message], tools: list[Tool]) -> str:
    sections = ["# Model Context\n"]
    sections.append("## Messages\n")
    for message in messages:
        sections.append(f"### {message.role}\n\n{message.content}\n")
    sections.append("## Visible Tools\n")
    for tool in tools:
        sections.append(f"### {tool.name}\n\n```json\n{json.dumps(_tool_dict(tool), indent=2, sort_keys=True)}\n```\n")
    return "\n".join(sections)


def _message_dict(message: Message) -> dict[str, str]:
    return {"role": message.role, "content": message.content}


def _tool_dict(tool: Tool) -> dict[str, Any]:
    return {"name": tool.name, "schema": dict(tool.schema)}


def _tool_call_dict(call: Any) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "args": call.args}
