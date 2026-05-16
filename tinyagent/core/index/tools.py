"""Model-visible code search tool."""

from __future__ import annotations

import time

from tinyagent.core.contracts import ToolRuntime
from tinyagent.core.index.manager import WorkspaceIndexManager
from tinyagent.core.index.types import IndexHit
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.token_utils import estimate_tokens, fits_token_budget
from tinyagent.core.tools.core import error_result, resolve_workspace_path, tool_env, visible_output

SUPPORTED_SEARCH_MODES = frozenset({"auto", "exact", "semantic", "hybrid", "fast"})


class SearchCodeTool:
    name = "search_code"
    runtime = ToolRuntime(parallel_safe=True, lock_key="workspace_index")
    schema = {
        "name": "search_code",
        "description": "Search workspace code and docs. Uses local index when available and rg fallback when needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "kind": {"type": "string"},
                "mode": {"type": "string", "enum": ["auto", "exact", "semantic", "hybrid", "fast"]},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "explain": {"type": "boolean"},
            },
            "required": ["query"],
        },
    }

    def __init__(self, manager: WorkspaceIndexManager | None = None) -> None:
        self.manager = manager

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        query = str(call.args.get("query") or "").strip()
        if not query:
            return ToolResult(tool_name=self.name, call_id=call.id, output="query is required", ok=False)
        path = str(call.args.get("path") or "").strip() or None
        kind = str(call.args.get("kind") or "").strip() or None
        mode = str(call.args.get("mode") or "auto")
        limit = min(max(int(call.args.get("limit", 10)), 1), 50)
        explain = bool(call.args.get("explain", False))
        try:
            if path is not None:
                resolve_workspace_path(state, path, allow_run_artifacts=False)
            if mode not in SUPPORTED_SEARCH_MODES:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call.id,
                    output=f"unsupported search mode: {mode}",
                    ok=False,
                    failure_kind="invalid_tool_args",
                    data={"mode": mode, "failure_kind": "invalid_tool_args"},
                )
            manager = _manager(state, self.manager)
            index = getattr(manager, "index", None)
            configure_runtime = getattr(index, "configure_runtime", None)
            if callable(configure_runtime):
                configure_runtime(env=tool_env(state), timeout_seconds=state.budgets.max_shell_timeout_seconds)
            status = manager.status()
            if mode == "semantic" and not status.semantic_ready:
                return ToolResult(
                    tool_name=self.name,
                    call_id=call.id,
                    output="semantic search is unavailable for the current workspace index",
                    ok=False,
                    failure_kind="unsupported_mode",
                    data={"mode": mode, "backend": status.backend, "semantic_ready": status.semantic_ready},
                )
            state.emit("index.sync.started", {"mode": "fast", "backend": status.backend})
            sync = manager.sync(root=state.workspace.root, mode="fast")
            state.emit(
                "index.sync.completed" if not sync.error else "index.sync.failed",
                {
                    "mode": sync.mode,
                    "backend": sync.backend,
                    "synced_file_count": sync.synced_file_count,
                    "stale_file_count": sync.stale_file_count,
                    "duration_ms": sync.duration_ms,
                    "error": sync.error,
                },
            )
            started = time.monotonic()
            hits = list(
                manager.search(
                    query,
                    root=state.workspace.root,
                    path=path,
                    kind=kind,
                    mode=mode,  # type: ignore[arg-type]
                    limit=limit,
                    explain=explain,
                )
            )
        except Exception as exc:
            return error_result(self.name, call, exc)
        duration_ms = int((time.monotonic() - started) * 1000)
        backend = hits[0].backend if hits else manager.status().backend
        output = _render_results(query, mode=mode, backend=backend, hits=hits)
        state.emit(
            "code.search.completed",
            {
                "query": query,
                "mode": mode,
                "path": path,
                "kind": kind,
                "backend": backend,
                "result_count": len(hits),
                "duration_ms": duration_ms,
                "rg_fallback": any(hit.backend == "rg" for hit in hits),
                "overlay_hits": sum(1 for hit in hits if hit.freshness == "overlay"),
                "semantic_used": False,
                "refs": [hit.ref for hit in hits],
            },
        )
        output_tokens = estimate_tokens(output)
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=output,
            content_preview=visible_output(output, state),
            data={
                "query": query,
                "mode": mode,
                "path": path,
                "kind": kind,
                "backend": backend,
                "result_count": len(hits),
                "output_tokens": output_tokens,
                "results": [_hit_data(hit) for hit in hits],
            },
            truncated=not fits_token_budget(output, state.budgets.max_tool_output_tokens_visible),
            summary=f"Code search returned {len(hits)} result(s).",
        )


def _manager(state: RunState, manager: WorkspaceIndexManager | None) -> WorkspaceIndexManager:
    if manager is not None:
        return manager
    if isinstance(state.workspace_index, WorkspaceIndexManager):
        return state.workspace_index
    return WorkspaceIndexManager.for_workspace(state.workspace.root)


def _render_results(query: str, *, mode: str, backend: str, hits: list[IndexHit]) -> str:
    lines = [
        f'Search code results for: "{query}"',
        f"mode: {mode}",
        f"backend: {backend}",
    ]
    if not hits:
        lines.append("No code results found.")
    for index, hit in enumerate(hits, start=1):
        span = f":{hit.line_start}-{hit.line_end}" if hit.line_start and hit.line_end else ""
        lines.extend(
            [
                "",
                f"{index}. {hit.path}{span}",
                f"   ref: {hit.ref}",
                f"   kind: {hit.kind}",
                f"   title: {hit.title}",
                f"   freshness: {hit.freshness}",
                f"   score: {hit.score:.2f}" if hit.score is not None else "   score: n/a",
            ]
        )
        if hit.explanation:
            lines.append(f"   why: {hit.explanation}")
        if hit.snippet:
            lines.extend(["   snippet:", f"   {hit.snippet}"])
    return "\n".join(lines)


def _hit_data(hit: IndexHit) -> dict[str, object]:
    return {
        "ref": hit.ref,
        "path": hit.path,
        "kind": hit.kind,
        "title": hit.title,
        "score": hit.score,
        "line_start": hit.line_start,
        "line_end": hit.line_end,
        "backend": hit.backend,
        "freshness": hit.freshness,
    }
