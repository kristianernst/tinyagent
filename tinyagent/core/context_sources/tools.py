"""Model-visible dynamic context tools."""

from __future__ import annotations

import time

from tinyagent.core.context_sources.registry import ContextRegistry, context_registry_for_state
from tinyagent.core.output import write_text_artifact
from tinyagent.core.path_safety import safe_artifact_name
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.tools.core import error_result, visible_output


class ContextSearchTool:
    name = "context_search"
    schema = {
        "name": "context_search",
        "description": (
            "Search dynamic context sources such as ContextFS, conversation history, "
            "past runs, skills, and indexed workspace content."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "source": {"type": "string"},
                "kind": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    }

    def __init__(self, registry: ContextRegistry | None = None) -> None:
        self.registry = registry

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        query = str(call.args.get("query") or "").strip()
        if not query:
            return ToolResult(tool_name=self.name, call_id=call.id, output="query is required", ok=False)
        source = str(call.args.get("source") or "").strip() or None
        kind = str(call.args.get("kind") or "").strip() or None
        limit = min(max(int(call.args.get("limit", 10)), 1), 50)
        started = time.monotonic()
        try:
            registry = _registry(state, self.registry)
            refs = registry.search(query, workspace=state.workspace.root, state=state, source=source, kind=kind, limit=limit)
        except Exception as exc:
            return error_result(self.name, call, exc)
        duration_ms = int((time.monotonic() - started) * 1000)
        lines = [f'Context search results for: "{query}"']
        for index, ref in enumerate(refs, start=1):
            lines.extend(
                [
                    "",
                    f"{index}. {ref.ref}",
                    f"   title: {ref.title}",
                    f"   source: {ref.source}",
                    f"   kind: {ref.kind}",
                    f"   score: {ref.score:.2f}" if ref.score is not None else "   score: n/a",
                    f"   summary: {ref.summary}",
                    f'   read: context_read({{"ref":"{ref.ref}"}})',
                ]
            )
        if not refs:
            lines.append("No context refs found.")
        output = "\n".join(lines)
        sources_used = sorted({ref.source for ref in refs})
        result_refs = [_ref_data(ref) for ref in refs]
        artifact = None
        if len(output) > state.budgets.max_command_output_chars_visible:
            artifact = write_text_artifact(state, f"context-search-{safe_artifact_name(call.id)}.txt", output, kind="context_search_output")
        state.emit(
            "context.search.completed",
            {
                "query": query,
                "source": source,
                "kind": kind,
                "result_count": len(refs),
                "sources_used": sources_used,
                "refs": [ref.ref for ref in refs],
                "duration_ms": duration_ms,
                "output_artifact": artifact,
            },
            artifact_refs=[artifact] if artifact else None,
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(output, state),
            artifact_path=artifact,
            data={
                "query": query,
                "source": source,
                "kind": kind,
                "result_count": len(refs),
                "sources_used": sources_used,
                "results": result_refs,
                "duration_ms": duration_ms,
                "output_artifact": artifact,
            },
            truncated=len(output) > state.budgets.max_command_output_chars_visible,
            summary=f"Context search returned {len(refs)} result(s).",
        )


class ContextReadTool:
    name = "context_read"
    schema = {
        "name": "context_read",
        "description": "Read a specific dynamic context ref returned by context_search. Supports bounded line ranges.",
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1},
                "max_lines": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
            "required": ["ref"],
        },
    }

    def __init__(self, registry: ContextRegistry | None = None) -> None:
        self.registry = registry

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        ref = str(call.args.get("ref") or "").strip()
        if not ref:
            return ToolResult(tool_name=self.name, call_id=call.id, output="ref is required", ok=False)
        start_line = max(int(call.args["start_line"]), 1) if "start_line" in call.args else None
        max_lines = min(max(int(call.args.get("max_lines", 400)), 1), 1000)
        try:
            chunk = _registry(state, self.registry).read(
                ref,
                workspace=state.workspace.root,
                state=state,
                start_line=start_line,
                max_lines=max_lines,
            )
        except Exception as exc:
            return error_result(self.name, call, exc)

        numbered = "\n".join(
            f"{line_number}: {line}"
            for line_number, line in enumerate(chunk.content.splitlines(), start=chunk.start_line or 1)
        )
        lines = [
            f"Ref: {chunk.ref}",
            f"Source: {chunk.source}",
            f"Lines: {chunk.start_line}-{chunk.end_line} of {chunk.total_lines}",
            "",
            numbered,
        ]
        output = "\n".join(lines)
        artifact = None
        if len(output) > state.budgets.max_command_output_chars_visible:
            artifact = write_text_artifact(state, f"context-read-{safe_artifact_name(call.id)}.txt", output, kind="context_read_output")
        if chunk.source == "skills":
            state.emit(
                "skill.loaded",
                {
                    "skill_id": chunk.metadata.get("skill_id"),
                    "name": chunk.title,
                    "source": chunk.metadata.get("source"),
                    "path": chunk.metadata.get("path"),
                    "instruction_chars": len(chunk.content),
                    "files": chunk.metadata.get("files") or [],
                    "truncated": chunk.truncated,
                },
            )
        state.emit(
            "context.ref.read",
            {
                "ref": chunk.ref,
                "source": chunk.source,
                "line_count": len(chunk.content.splitlines()),
                "truncated": chunk.truncated,
                "output_artifact": artifact,
            },
            artifact_refs=[artifact] if artifact else None,
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(output, state),
            artifact_path=artifact,
            data={
                "ref": chunk.ref,
                "source": chunk.source,
                "line_count": len(chunk.content.splitlines()),
                "truncated": chunk.truncated,
                "output_artifact": artifact,
            },
            truncated=chunk.truncated or artifact is not None,
            summary=f"Read context ref {chunk.ref}.",
        )


def _registry(state: RunState, registry: ContextRegistry | None) -> ContextRegistry:
    if registry is not None:
        return registry
    return context_registry_for_state(state)


def _ref_data(ref) -> dict[str, object]:
    return {
        "ref": ref.ref,
        "source": ref.source,
        "title": ref.title,
        "kind": ref.kind,
        "summary": ref.summary,
        "score": ref.score,
        "path": ref.path,
        "line_start": ref.line_start,
        "line_end": ref.line_end,
    }
