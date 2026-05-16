# ruff: noqa: E402
"""Runnable web-research example built on the tinyagent harness."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from math import ceil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tinyagent.core.context import ContextBuilder, ContextConfig, ContextPlan, compact_state
from tinyagent.core.contracts import ProfileRuntimeCapabilities, Tool
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import LocalPolicy
from tinyagent.core.providers.openai_compat import OpenAICompatibleConfig, OpenAICompatibleProvider
from tinyagent.core.providers.openai_responses import OpenAIResponsesConfig, OpenAIResponsesProvider
from tinyagent.core.sdk import Agent
from tinyagent.core.state import FinishDecision, Message, ModelResponse, PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult
from tinyagent.core.token_utils import clip_text_to_token_budget, estimate_tokens, token_budget_to_text_limit
from tinyagent.core.tools.core import capture_tool_output, duration_ms, error_result, resolve_workspace_path

USER_AGENT = "tinyagent-web-searcher/0.1 (+https://github.com/tinyagent/examples)"
DEFAULT_TASK = "Do deep research on NVIDIA stock and write a sourced research_report.md."
REPORT_PATH = "research_report.md"
MAX_REPORT_BYTES = 128_000


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    def to_json_dict(self) -> dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


@dataclass(frozen=True)
class FetchedDocument:
    url: str
    title: str
    text: str

    def to_json_dict(self) -> dict[str, str]:
        return {"url": self.url, "title": self.title, "text": self.text}


class FixtureWebBackend:
    name = "fixture"

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        lowered = query.lower()
        if any(token in lowered for token in ("flight", "fare", "airfare", "cph", "sfo", "tokyo")):
            results = FLIGHT_RESULTS
        else:
            results = STOCK_RESULTS
        return results[:max_results]

    def fetch(self, url: str, *, max_tokens: int) -> FetchedDocument:
        document = FIXTURE_DOCUMENTS.get(url)
        if document is None:
            raise ValueError(f"fixture URL not found: {url}")
        text_limit = token_budget_to_text_limit(max_tokens)
        return FetchedDocument(url=url, title=document["title"], text=document["text"][:text_limit])


class DuckDuckGoWebBackend:
    name = "duckduckgo"

    def __init__(self, *, timeout_seconds: int = 20) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, max_results: int) -> list[SearchResult]:
        params = urllib.parse.urlencode({"q": query})
        url = f"https://duckduckgo.com/html/?{params}"
        html_text = _read_url(url, timeout_seconds=self.timeout_seconds, max_bytes=1_000_000)
        results = _parse_duckduckgo_results(html_text, max_results=max_results)
        if not results:
            raise ValueError("DuckDuckGo returned no parseable results.")
        return results

    def fetch(self, url: str, *, max_tokens: int) -> FetchedDocument:
        text_limit = token_budget_to_text_limit(max_tokens)
        raw = _read_url(url, timeout_seconds=self.timeout_seconds, max_bytes=max(text_limit * 6, 200_000))
        title, text = _html_to_text(raw)
        if not text.strip():
            text = raw
        return FetchedDocument(url=url, title=title or url, text=text[:text_limit])


class WebSearchTool:
    name = "web_search"
    schema = {
        "name": "web_search",
        "description": "Search the web once for a query and return compact result titles, URLs, and snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 8},
            },
            "required": ["query"],
        },
    }

    def __init__(self, backend: FixtureWebBackend | DuckDuckGoWebBackend) -> None:
        self.backend = backend

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        started = time.monotonic()
        try:
            query = str(call.args["query"]).strip()
            if not query:
                raise ValueError("query is required")
            max_results = min(max(int(call.args.get("max_results", 5)), 1), 8)
            results = self.backend.search(query, max_results=max_results)
            output = _render_search_results(query, results, backend=self.backend.name)
            captured = capture_tool_output(state, call, output, prefix="web-search-output", kind="web_search_output")
            return captured.tool_result(
                self.name,
                call,
                ok=True,
                duration_ms=duration_ms(started),
                summary=f"{len(results)} result(s) for {query!r}",
                data={
                    "backend": self.backend.name,
                    "query": query,
                    "result_count": len(results),
                    "results": [result.to_json_dict() for result in results[:3]],
                    **captured.data,
                    "duration_ms": duration_ms(started),
                },
                metadata={"backend": self.backend.name},
                failure=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                call_id=call.id,
                output=f"web_search error: {exc}",
                ok=False,
                data={"backend": self.backend.name, "error_type": type(exc).__name__, "failure_kind": "web_search_failed"},
                failure_kind="web_search_failed",
                summary=f"web_search error: {exc}",
                content_preview=f"web_search error: {exc}",
                duration_ms=duration_ms(started),
            )


class FetchUrlTool:
    name = "fetch_url"
    schema = {
        "name": "fetch_url",
        "description": "Fetch one prior web_search result and return readable text. Fetch two sources before writing.",
        "parameters": {
            "type": "object",
            "properties": {
                "result_number": {"type": "integer", "minimum": 1, "maximum": 8, "description": "Search result number to fetch."},
                "url": {"type": "string", "description": "Exact URL from a prior web_search result."},
                "max_tokens": {"type": "integer", "minimum": 125, "maximum": 5000},
            },
        },
    }

    def __init__(self, backend: FixtureWebBackend | DuckDuckGoWebBackend) -> None:
        self.backend = backend

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        started = time.monotonic()
        try:
            requested_url = str(call.args.get("url") or "").strip()
            url = _select_fetch_url(
                state,
                requested_url=requested_url,
                result_number=call.args.get("result_number"),
                backend=self.backend.name,
            )
            if not url:
                raise ValueError("url or result_number is required")
            max_tokens = min(max(int(call.args.get("max_tokens", 1500)), 125), 5_000)
            document = self.backend.fetch(url, max_tokens=max_tokens)
            remap_note = f"Requested URL was remapped from {requested_url}.\n" if requested_url and requested_url != url else ""
            output = "\n".join(
                [
                    f"URL: {document.url}",
                    f"Title: {document.title}",
                    "",
                    remap_note,
                    document.text,
                ]
            ).strip()
            captured = capture_tool_output(state, call, output, prefix="fetch-url-output", kind="fetch_url_output")
            return captured.tool_result(
                self.name,
                call,
                ok=True,
                duration_ms=duration_ms(started),
                summary=f"Fetched {document.title[:120]}",
                data={
                    "backend": self.backend.name,
                    "url": document.url,
                    "requested_url": requested_url,
                    "title": document.title,
                    "text_tokens": estimate_tokens(document.text),
                    **captured.data,
                    "duration_ms": duration_ms(started),
                },
                metadata={"backend": self.backend.name, "url": document.url},
                failure=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.name,
                call_id=call.id,
                output=f"fetch_url error: {exc}",
                ok=False,
                data={"backend": self.backend.name, "error_type": type(exc).__name__, "failure_kind": "fetch_url_failed"},
                failure_kind="fetch_url_failed",
                summary=f"fetch_url error: {exc}",
                content_preview=f"fetch_url error: {exc}",
                duration_ms=duration_ms(started),
            )


class WriteReportTool:
    name = "write_report"
    schema = {
        "name": "write_report",
        "description": f"Write the final sourced research report to {REPORT_PATH}.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": (
                        "Complete markdown report. Must include Summary, Findings, Source Notes with exact fetched URLs, "
                        "Caveats, and Next Checks."
                    ),
                }
            },
            "required": ["content"],
            "additionalProperties": False,
        },
    }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        started = time.monotonic()
        try:
            content = str(call.args["content"]).strip()
            if not content:
                raise ValueError("content is required")
            if len(content.encode()) > MAX_REPORT_BYTES:
                raise ValueError(f"report content exceeds {MAX_REPORT_BYTES} bytes")
            path = resolve_workspace_path(state, REPORT_PATH)
            path.write_text(f"{content}\n", encoding="utf-8")
            output = f"Wrote {REPORT_PATH} with write_report.\n"
            captured = capture_tool_output(state, call, output, prefix="edit-output", kind="edit_output")
            elapsed_ms = duration_ms(started)
            state.emit(
                "file.edited",
                {
                    "tool_call_id": call.id,
                    "tool": self.name,
                    "paths": [REPORT_PATH],
                    "ok": True,
                    **captured.data,
                    "duration_ms": elapsed_ms,
                },
            )
            return captured.tool_result(
                self.name,
                call,
                ok=True,
                duration_ms=elapsed_ms,
                summary=output.strip(),
                data={"paths": [REPORT_PATH], **captured.data, "duration_ms": elapsed_ms},
                metadata={"paths": [REPORT_PATH]},
                failure=False,
            )
        except Exception as exc:
            return error_result(self.name, call, exc)


class WebResearchPolicy:
    def __init__(self, *, max_searches: int = 1, max_fetches: int = 2, min_fetches: int = 2) -> None:
        self.local = LocalPolicy()
        self.max_searches = max_searches
        self.max_fetches = max_fetches
        self.min_fetches = min_fetches

    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        if call.name == "web_search" and _successful_tool_count(state, "web_search") >= self.max_searches:
            return PolicyDecision.deny("web_search limit reached for this staged example", permission="network")
        if call.name == "fetch_url" and _successful_tool_count(state, "fetch_url") >= self.max_fetches:
            return PolicyDecision.deny("fetch_url limit reached for this staged example", permission="network")
        if call.name in {"web_search", "fetch_url"}:
            return PolicyDecision.allow("web research example tool", permission="network")
        if call.name == "write_report":
            if _successful_tool_count(state, "fetch_url") < self.min_fetches:
                return PolicyDecision.deny(
                    f"write_report requires {self.min_fetches} fetched source(s) first",
                    permission="filesystem",
                )
            return PolicyDecision.allow(f"write_report only writes {REPORT_PATH}", permission="filesystem")
        return self.local.evaluate(call, state)


class WebResearchProfile:
    name = "web-researcher"
    profile_variant = "web-searcher-example"
    context_policy_name = "web-research-v1"
    skill_policy_name = "none"
    tool_surface_name = "web-research"
    runtime_capabilities = ProfileRuntimeCapabilities(
        skills=False,
        dynamic_context=False,
        workspace_index=False,
        extensions=False,
        contextfs=True,
        tool_names=("web_search", "fetch_url", "write_report"),
    )
    visible_tool_names = ("web_search", "fetch_url", "write_report")

    def __init__(self, *, compact_after_tool_steps: int = 4, max_searches: int = 1, target_fetches: int = 2) -> None:
        self.max_searches = max(max_searches, 1)
        self.target_fetches = max(target_fetches, 1)
        self.fetches_per_search = max(1, ceil(self.target_fetches / self.max_searches))
        self.context_config = ContextConfig(
            project_instruction_max_tokens=2_000,
            max_recent_tool_tokens=3_000,
            compact_after_tool_steps=compact_after_tool_steps,
            compact_at_tokens=24_000,
            reserve_output_tokens=4_000,
        )

    def system_prompt(self) -> str:
        return self._system_prompt_for_state(None)

    def build_context(self, state: RunState, *, visible_tools: Sequence[Tool] | None = None):
        visible_tool_names = [tool.name for tool in visible_tools] if visible_tools is not None else self.visible_tool_names
        return ContextBuilder(system_prompt=self._system_prompt_for_state(state), config=self._context_config_for_state(state)).build(
            state,
            plan=self.plan_next_context(state),
            visible_tool_names=visible_tool_names,
        )

    def _system_prompt_for_state(self, state: RunState | None) -> str:
        lines = [
            "You are a web research agent running inside the tinyagent harness.",
            "Use web_search to find candidate sources, then fetch_url to inspect important sources before concluding.",
            (
                f"Use this staged flow: call web_search up to {self.max_searches} time(s), "
                f"fetch at least {self.target_fetches} source(s), then call write_report."
            ),
            "When calling fetch_url, use result_number from the web_search output or an exact URL shown there.",
            "For market, stock, travel, and price questions, call out timing, uncertainty, and source limitations.",
            f"Before your final answer, write a substantive sourced report to {REPORT_PATH} with write_report.",
            "The report must include Summary, Findings, Source Notes with exact fetched URLs, Caveats, and Next Checks.",
            "Do not write placeholders such as 'research in progress'.",
            "Keep tool use purposeful. Use the fetched source digest below when recent tool output has been compacted.",
        ]
        if state is not None:
            digest = _source_digest(state) if state.context_checkpoint else ""
            if digest:
                lines.extend(["", digest])
            if _wrote_report(state) and not _report_ready(state):
                lines.extend(
                    [
                        "",
                        f"The latest {REPORT_PATH} is incomplete. Rewrite it now with the required sections and exact fetched URLs.",
                    ]
                )
        return "\n".join(lines)

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return self.build_context(state).messages

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        search_count = _successful_tool_count(state, "web_search")
        fetch_count = _successful_tool_count(state, "fetch_url")
        if _report_ready(state):
            names = ()
        elif fetch_count >= self.target_fetches:
            names = ("write_report",)
        elif search_count == 0:
            names = ("web_search",)
        elif search_count < self.max_searches and fetch_count >= search_count * self.fetches_per_search:
            names = ("web_search",)
        else:
            names = ("fetch_url",)
        return [all_tools[name] for name in names if name in all_tools]

    def should_continue(self, state: RunState) -> bool:
        return not state.done

    def should_finish(self, state: RunState) -> bool:
        return _successful_tool_count(state, "fetch_url") >= self.target_fetches and _report_ready(state)

    def before_finish(self, state: RunState, response: ModelResponse) -> FinishDecision:
        if not _has_successful_tool(state, "web_search"):
            return FinishDecision.blocked("finish blocked: search the web first", "Call web_search before finalizing.")
        if _successful_tool_count(state, "fetch_url") < self.target_fetches:
            return FinishDecision.blocked(
                f"finish blocked: fetch {self.target_fetches} sources",
                f"Call fetch_url on {self.target_fetches} sources before finalizing.",
            )
        if _wrote_report(state) and not _report_ready(state):
            digest = _source_digest(state)
            return FinishDecision.blocked(
                f"finish blocked: {REPORT_PATH} is incomplete",
                (
                    f"Rewrite {REPORT_PATH} with Summary, Findings, Source Notes with exact fetched URLs, "
                    "Caveats, and Next Checks. Do not use placeholder text."
                    + (f"\n\n{digest}" if digest else "")
                ),
            )
        if not _wrote_report(state):
            return FinishDecision.blocked(
                f"finish blocked: write {REPORT_PATH}",
                f"Write {REPORT_PATH} with write_report before finalizing.",
            )
        last_step = state.tool_steps[-1] if state.tool_steps else None
        if last_step is not None and not last_step.result.ok and "failed" not in (response.content or "").lower():
            return FinishDecision.blocked(
                "finish blocked: last web tool failed and final answer did not report it",
                "Report the failed tool result or continue with another source.",
            )
        return FinishDecision.allowed()

    def should_compact(self, state: RunState) -> bool:
        new_steps = len(state.tool_steps) - state.context_checkpoint_tool_step_count
        return new_steps > 0 and (
            new_steps >= self.context_config.compact_after_tool_steps
            or state.context_token_estimate >= self.context_config.effective_compact_at_tokens
        )

    def compact(self, state: RunState) -> None:
        compact_state(state, self._context_config_for_state(state))

    def plan_next_context(self, state: RunState) -> ContextPlan:
        if _wrote_report(state):
            return ContextPlan(mode="finish", reason="report written; final answer can cite report path")
        if len(state.tool_steps) >= 4:
            return ContextPlan(mode="summarize", recent_tail_budget=2_000, reason="synthesize fetched sources into report")
        if state.tool_steps:
            return ContextPlan(mode="explore", recent_tail_budget=2_500, reason="continue source discovery and fetching")
        return ContextPlan(mode="explore", reason="initial web research")

    def _context_config_for_state(self, state: RunState) -> ContextConfig:
        capabilities = (state.model_spec or {}).get("capabilities")
        if not isinstance(capabilities, dict):
            return self.context_config
        context_window = capabilities.get("context_window")
        max_output_tokens = capabilities.get("max_output_tokens")
        if not isinstance(context_window, int) or not isinstance(max_output_tokens, int):
            return self.context_config
        return self.context_config.with_model_budget(context_window=context_window, max_output_tokens=max_output_tokens)


def build_provider(args: argparse.Namespace, task: str):
    if args.provider == "fake":
        return FakeModelProvider(_fake_web_responses(task), model="fake-web-researcher")

    extra_body = {"temperature": args.temperature}
    if args.extra_body_json:
        extra_body.update(json.loads(args.extra_body_json))

    if args.provider == "openai-codex":
        values = dict(os.environ)
        if args.model:
            values["TINYAGENT_MODEL_NAME"] = args.model
        return OpenAIResponsesProvider.codex_from_env(values)

    model = args.model or _discover_model(args.base_url, args.api_key, timeout_seconds=args.timeout_seconds) or "local-model"
    if args.provider == "openai-responses":
        return OpenAIResponsesProvider(
            OpenAIResponsesConfig(
                base_url=args.base_url,
                api_key=args.api_key,
                model=model,
                timeout_seconds=args.timeout_seconds,
                context_window=args.context_window,
                max_output_tokens=args.max_output_tokens,
                extra_body=extra_body,
            )
        )
    return OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            base_url=args.base_url,
            api_key=args.api_key,
            model=model,
            timeout_seconds=args.timeout_seconds,
            context_window=args.context_window,
            max_output_tokens=args.max_output_tokens,
            extra_body=extra_body,
        )
    )


def build_web_backend(args: argparse.Namespace) -> FixtureWebBackend | DuckDuckGoWebBackend:
    backend = args.web_backend
    if backend is None:
        backend = "fixture" if args.provider == "fake" else "duckduckgo"
    if backend == "fixture":
        return FixtureWebBackend()
    return DuckDuckGoWebBackend(timeout_seconds=args.web_timeout_seconds)


async def run_example(args: argparse.Namespace) -> int:
    workspace = args.workspace.expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    task = args.task or DEFAULT_TASK
    backend = build_web_backend(args)
    provider = build_provider(args, task)
    profile = WebResearchProfile(
        compact_after_tool_steps=args.compact_after_tool_steps,
        max_searches=args.max_searches,
        target_fetches=args.target_fetches,
    )
    agent = Agent.create(
        workspace=workspace,
        provider=provider,
        profile=profile,
        tools=[WebSearchTool(backend), FetchUrlTool(backend), WriteReportTool()],
        policy=WebResearchPolicy(
            max_searches=args.max_searches,
            max_fetches=args.max_fetches or args.target_fetches,
            min_fetches=args.target_fetches,
        ),
        budgets=RunBudgets(max_model_calls=args.max_model_calls, max_tool_calls=args.max_tool_calls, max_run_seconds=args.max_run_seconds),
        workspace_mode="current",
        approval_mode="yolo",
    )

    handle = await agent.start(task, run_id=args.run_id, output_dir=args.output_dir)
    if args.stream_events:
        async for event in handle.events():
            rendered = _render_event_line(event.type, event.data)
            if rendered:
                print(rendered)
    result = await handle.result()
    _print_summary(result, provider=provider.name, web_backend=backend.name, workspace=workspace)
    return 0 if result.status == "completed" else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return asyncio.run(run_example(args))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"web_searcher error: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a tinyagent web-searcher example.")
    parser.add_argument("task", nargs="?", default=DEFAULT_TASK)
    parser.add_argument("--provider", choices=["fake", "openai-compatible", "openai-responses", "openai-codex"], default="fake")
    parser.add_argument("--workspace", type=Path, default=Path("/tmp/tinyagent-web-searcher"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id", default="web-searcher-example")
    parser.add_argument("--web-backend", choices=["fixture", "duckduckgo"])
    parser.add_argument("--base-url", default=os.environ.get("TINYAGENT_MODEL_BASE_URL", "http://127.0.0.1:8080/v1"))
    parser.add_argument("--api-key", default=os.environ.get("TINYAGENT_MODEL_API_KEY", "local"))
    parser.add_argument("--model", default=os.environ.get("TINYAGENT_MODEL_NAME"))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("TINYAGENT_MODEL_TIMEOUT_SECONDS", "120")))
    parser.add_argument("--context-window", type=int, default=int(os.environ.get("TINYAGENT_MODEL_CONTEXT_WINDOW", "128000")))
    parser.add_argument("--max-output-tokens", type=int, default=int(os.environ.get("TINYAGENT_MODEL_MAX_OUTPUT_TOKENS", "8000")))
    parser.add_argument("--extra-body-json")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--web-timeout-seconds", type=int, default=20)
    parser.add_argument("--max-model-calls", type=int, default=14)
    parser.add_argument("--max-tool-calls", type=int, default=30)
    parser.add_argument("--max-run-seconds", type=int, default=300)
    parser.add_argument("--compact-after-tool-steps", type=int, default=4)
    parser.add_argument("--max-searches", type=int, default=1)
    parser.add_argument("--target-fetches", type=int, default=2)
    parser.add_argument("--max-fetches", type=int)
    parser.add_argument("--stream-events", action="store_true")
    return parser


def _fake_web_responses(task: str) -> list[ModelResponse]:
    lowered = task.lower()
    if any(token in lowered for token in ("flight", "fare", "airfare", "cph", "sfo", "tokyo")):
        return [
            ModelResponse(
                tool_calls=(
                    ToolCall(name="web_search", args={"query": "Copenhagen to Tokyo August 2026 flight fare trend", "max_results": 4}),
                )
            ),
            ModelResponse(tool_calls=(ToolCall(name="fetch_url", args={"url": "fixture://flights/cph-tyo-fares", "max_tokens": 1250}),)),
            ModelResponse(tool_calls=(ToolCall(name="fetch_url", args={"url": "fixture://flights/booking-patterns", "max_tokens": 1250}),)),
            ModelResponse(tool_calls=(ToolCall(name="write_report", args={"content": FLIGHT_REPORT}),)),
            ModelResponse(
                content=f"Flight research complete. I wrote {REPORT_PATH} with fare ranges, caveats, and next checks.",
                finish_reason="stop",
            ),
        ]
    return [
        ModelResponse(
            tool_calls=(ToolCall(name="web_search", args={"query": "NVIDIA stock recent earnings AI data center risks", "max_results": 4}),)
        ),
        ModelResponse(tool_calls=(ToolCall(name="fetch_url", args={"url": "fixture://stocks/nvda-earnings", "max_tokens": 1250}),)),
        ModelResponse(tool_calls=(ToolCall(name="fetch_url", args={"url": "fixture://stocks/nvda-risks", "max_tokens": 1250}),)),
        ModelResponse(tool_calls=(ToolCall(name="write_report", args={"content": STOCK_REPORT}),)),
        ModelResponse(
            content=f"Stock research complete. I wrote {REPORT_PATH} with sourced bullets and open questions.",
            finish_reason="stop",
        ),
    ]


def _has_successful_tool(state: RunState, tool_name: str) -> bool:
    return any(step.call.name == tool_name and step.result.ok for step in state.tool_steps)


def _successful_tool_count(state: RunState, tool_name: str) -> int:
    return sum(1 for step in state.tool_steps if step.call.name == tool_name and step.result.ok)


def _select_fetch_url(state: RunState, *, requested_url: str, result_number: object, backend: str) -> str:
    urls = _latest_search_result_urls(state)
    if result_number is not None:
        index = int(result_number) - 1
        if index < 0 or index >= len(urls):
            raise ValueError(f"result_number must refer to one of {len(urls)} search result(s)")
        return urls[index]
    if requested_url in urls:
        return requested_url
    if backend == "fixture" and urls:
        return _next_unfetched_url(state, urls)
    return requested_url


def _latest_search_result_urls(state: RunState) -> list[str]:
    for step in reversed(state.tool_steps):
        if step.call.name != "web_search" or not step.result.ok:
            continue
        results = step.result.data.get("results")
        if not isinstance(results, list):
            return []
        urls: list[str] = []
        for result in results:
            if isinstance(result, dict) and isinstance(result.get("url"), str):
                urls.append(result["url"])
        return urls
    return []


def _next_unfetched_url(state: RunState, urls: Sequence[str]) -> str:
    fetched = {
        str(step.result.data.get("url"))
        for step in state.tool_steps
        if step.call.name == "fetch_url" and step.result.ok and step.result.data.get("url")
    }
    for url in urls:
        if url not in fetched:
            return url
    return urls[0] if urls else ""


def _wrote_report(state: RunState) -> bool:
    return _latest_report_content(state) is not None


def _report_ready(state: RunState) -> bool:
    content = _latest_report_content(state)
    if content is None:
        return False
    lowered = content.lower()
    if len(content) < 450:
        return False
    if "research in progress" in lowered or "to be determined" in lowered:
        return False
    required = ("summary", "source", "caveat")
    if not all(word in lowered for word in required):
        return False
    fetched_urls = _fetched_urls(state)
    if fetched_urls:
        return all(url in content for url in fetched_urls[:2])
    return "fixture://" in content or "http://" in content or "https://" in content


def _latest_report_content(state: RunState) -> str | None:
    for step in reversed(state.tool_steps):
        if step.call.name != "write_report" or not step.result.ok:
            continue
        return str(step.call.args.get("content") or "")
    return None


def _fetched_urls(state: RunState) -> list[str]:
    urls: list[str] = []
    for step in state.tool_steps:
        if step.call.name != "fetch_url" or not step.result.ok:
            continue
        data = step.result.data if isinstance(step.result.data, dict) else {}
        url = str(data.get("url") or step.call.args.get("url") or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def _source_digest(state: RunState, *, max_tokens: int = 500) -> str:
    docs: list[tuple[str, str, str]] = []
    for step in state.tool_steps:
        if step.call.name != "fetch_url" or not step.result.ok:
            continue
        data = step.result.data if isinstance(step.result.data, dict) else {}
        url = str(data.get("url") or step.call.args.get("url") or "").strip()
        title = str(data.get("title") or url or "Fetched source").strip()
        excerpt = _source_excerpt(str(step.result.output or ""))
        if url:
            docs.append((url, title, excerpt))
    if not docs:
        return ""
    per_doc_tokens = max(65, max_tokens // max(len(docs), 1) - 30)
    lines = [
        "Fetched source digest for the report:",
        "Use these exact fetched URLs in Source Notes.",
    ]
    for url, title, excerpt in docs[:4]:
        lines.append(f"- {url} ({title}): {clip_text_to_token_budget(excerpt, per_doc_tokens)}")
    return "\n".join(lines)


def _source_excerpt(output: str) -> str:
    lines = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("URL:", "Title:")):
            continue
        lines.append(stripped)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _clip_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(limit - 3, 0)].rstrip() + "..."


def _render_search_results(query: str, results: Sequence[SearchResult], *, backend: str) -> str:
    lines = [f"backend: {backend}", f"query: {query}", ""]
    for index, result in enumerate(results, start=1):
        lines.extend(
            [
                f"{index}. {result.title}",
                f"   url: {result.url}",
                f"   snippet: {result.snippet}",
            ]
        )
    return "\n".join(lines)


def _render_event_line(event_type: str, data: Mapping[str, Any]) -> str:
    if event_type == "model.call.started":
        return f"model_call: {data.get('model_call_id')} tools={data.get('tool_count')} tokens~pending"
    if event_type == "context.built":
        return f"context: tokens~{data.get('token_estimate')} tools={','.join(data.get('visible_tools') or [])}"
    if event_type == "tool.execution.completed":
        return f"tool: {data.get('tool')} ok={data.get('ok')}"
    if event_type == "checkpoint.completed":
        return f"checkpoint: {data.get('checkpoint_artifact')}"
    if event_type in {"run.completed", "run.failed"}:
        return f"{event_type}: {data.get('status') or data.get('reason') or ''}".strip()
    return ""


def _print_summary(result, *, provider: str, web_backend: str, workspace: Path) -> None:
    report = workspace / REPORT_PATH
    print(f"status: {result.status}")
    print(f"provider: {provider}")
    print(f"web_backend: {web_backend}")
    print(f"workspace: {workspace}")
    print(f"output_dir: {result.output_dir}")
    print(f"report: {report if report.exists() else 'missing'}")
    print(f"web_search_calls: {_event_tool_count(result.events, 'web_search')}")
    print(f"fetch_url_calls: {_event_tool_count(result.events, 'fetch_url')}")
    print(f"context_checkpoints: {sum(1 for event in result.events if event.type == 'checkpoint.completed')}")
    if result.failure_reason:
        print(f"failure_reason: {result.failure_reason}")


def _event_tool_count(events, tool_name: str) -> int:
    return sum(1 for event in events if event.type == "tool.execution.completed" and event.data.get("tool") == tool_name)


def _discover_model(base_url: str, api_key: str, *, timeout_seconds: int) -> str | None:
    url = f"{base_url.rstrip('/')}/models"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_key}", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=min(timeout_seconds, 10)) as response:
            payload = json.loads(response.read().decode())
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if isinstance(first, dict) and isinstance(first.get("id"), str):
        return first["id"]
    return None


def _read_url(url: str, *, timeout_seconds: int, max_bytes: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"HTTP {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"request failed for {url}: {exc.reason}") from exc
    if len(data) > max_bytes:
        data = data[:max_bytes]
    return data.decode("utf-8", errors="replace")


def _parse_duckduckgo_results(html_text: str, *, max_results: int) -> list[SearchResult]:
    results: list[SearchResult] = []
    pattern = re.compile(r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.I | re.S)
    for match in pattern.finditer(html_text):
        url = _clean_duckduckgo_url(html.unescape(match.group("href")))
        title = _strip_tags(match.group("title"))
        tail = html_text[match.end() : match.end() + 1800]
        snippet_match = re.search(r'class="result__snippet"[^>]*>(?P<snippet>.*?)</', tail, re.I | re.S)
        snippet = _strip_tags(snippet_match.group("snippet")) if snippet_match else ""
        if url and title:
            results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= max_results:
            break
    return results


def _clean_duckduckgo_url(url: str) -> str:
    if url.startswith("//"):
        url = f"https:{url}"
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return query["uddg"][0]
    return url


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in {"p", "br", "li", "div", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data).strip()
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
        else:
            self.parts.append(text)


def _html_to_text(html_text: str) -> tuple[str, str]:
    parser = _TextExtractor()
    parser.feed(html_text)
    lines = [line.strip() for line in "\n".join(parser.parts).splitlines()]
    text = "\n".join(line for line in lines if line)
    return parser.title.strip(), text


def _strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value))).strip()


STOCK_RESULTS = [
    SearchResult(
        title="NVIDIA quarterly results and data-center demand",
        url="fixture://stocks/nvda-earnings",
        snippet="Revenue growth remains driven by data-center accelerators, but comparisons are getting harder.",
    ),
    SearchResult(
        title="NVIDIA valuation and concentration risks",
        url="fixture://stocks/nvda-risks",
        snippet="Analysts debate hyperscaler capex durability, gross margin normalization, and export controls.",
    ),
    SearchResult(
        title="Semiconductor supply chain context",
        url="fixture://stocks/semis-supply",
        snippet="Advanced packaging and memory supply remain relevant constraints for AI accelerator ramps.",
    ),
]

FLIGHT_RESULTS = [
    SearchResult(
        title="CPH to Tokyo fare snapshot",
        url="fixture://flights/cph-tyo-fares",
        snippet="Recent sample fares cluster around one-stop itineraries with sharp weekend variance.",
    ),
    SearchResult(
        title="Long-haul booking timing patterns",
        url="fixture://flights/booking-patterns",
        snippet="International leisure fares often move materially inside the 2 to 5 month booking window.",
    ),
    SearchResult(
        title="Route and stopover options",
        url="fixture://flights/route-options",
        snippet="Common routings include Helsinki, Doha, Istanbul, Frankfurt, Amsterdam, and Paris connections.",
    ),
]

FIXTURE_DOCUMENTS = {
    "fixture://stocks/nvda-earnings": {
        "title": "NVIDIA quarterly results and data-center demand",
        "text": (
            "Fixture source, captured for deterministic harness testing.\n"
            "NVIDIA's recent growth narrative is still dominated by data-center AI accelerators. "
            "The key research questions are whether hyperscaler capital expenditure remains durable, whether networking "
            "and software attach "
            "rates broaden the revenue base, and whether supply catches up fast enough to compress pricing. Margin quality matters because "
            "investors may punish even strong growth if gross margins normalize faster than expected."
        ),
    },
    "fixture://stocks/nvda-risks": {
        "title": "NVIDIA valuation and concentration risks",
        "text": (
            "Fixture source, captured for deterministic harness testing.\n"
            "The main risk cluster is concentration: a small group of large cloud buyers, export-control exposure, "
            "and the possibility that "
            "custom silicon reduces future accelerator demand. Valuation risk is separate from business quality. "
            "A good report should avoid "
            "treating strong products as automatic upside when expectations are already high."
        ),
    },
    "fixture://stocks/semis-supply": {
        "title": "Semiconductor supply chain context",
        "text": (
            "Fixture source, captured for deterministic harness testing.\n"
            "Advanced packaging, HBM memory, power delivery, and datacenter buildout capacity remain the important bottlenecks to track."
        ),
    },
    "fixture://flights/cph-tyo-fares": {
        "title": "CPH to Tokyo fare snapshot",
        "text": (
            "Fixture source, captured for deterministic harness testing.\n"
            "Sample one-stop Copenhagen to Tokyo economy itineraries are usually cheaper than direct options when direct "
            "capacity is limited. "
            "In the fixture snapshot, reasonable round-trip targets are 6500 to 9000 DKK for economy and materially "
            "higher for premium cabins. "
            "Search dates, baggage, refundability, and airport choice can move the result by several thousand DKK."
        ),
    },
    "fixture://flights/booking-patterns": {
        "title": "Long-haul booking timing patterns",
        "text": (
            "Fixture source, captured for deterministic harness testing.\n"
            "For long-haul leisure trips, useful checks include flexible date grids, nearby airports, separate outbound "
            "and inbound carriers, "
            "and price alerts. The report should avoid claiming live fares unless a live booking source was fetched in the run."
        ),
    },
    "fixture://flights/route-options": {
        "title": "Route and stopover options",
        "text": (
            "Fixture source, captured for deterministic harness testing.\n"
            "Likely connection hubs include Helsinki, Doha, Istanbul, Frankfurt, Amsterdam, and Paris. Shorter layovers may cost more."
        ),
    },
}

STOCK_REPORT = """# NVIDIA Stock Research Fixture

## Summary
- Data-center AI accelerator demand is the main growth driver in the fixture sources.
- The biggest debate is not whether the business is strong, but how much durability is already priced in.
- Watch hyperscaler capex, export-control exposure, gross margin normalization, custom silicon substitution, and supply bottlenecks.

## Source Notes
- fixture://stocks/nvda-earnings: demand and margin quality framing.
- fixture://stocks/nvda-risks: concentration, valuation, and policy risks.

## Caveats
- This fixture is deterministic harness data, not a live market quote.
- Treat it as a structure and protocol test unless the run uses live web sources.

## Open Questions
- Are cloud customer orders broadening or still concentrated?
- Are margins holding because of scarcity, mix, or sustainable software/networking attach?
- Has consensus already priced in the next product-cycle ramp?
"""

FLIGHT_REPORT = """# CPH to Tokyo Flight Research Fixture

## Summary
- Fixture economy round-trip targets cluster around 6500 to 9000 DKK, but this is not a live fare quote.
- One-stop itineraries are likely the practical baseline; direct availability and weekend timing can change the price materially.
- Good next checks are flexible date grids, nearby airport options, baggage rules, and price alerts.

## Source Notes
- fixture://flights/cph-tyo-fares: sample fare range and caveats.
- fixture://flights/booking-patterns: timing and price-alert strategy.

## Caveats
Do not treat this fixture as live availability. Run with --provider openai-compatible
--web-backend duckduckgo for a live source-gathering pass.
"""


if __name__ == "__main__":
    raise SystemExit(main())
