# ruff: noqa: E402
"""Run the web-searcher example repeatedly and summarize harness evidence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples" / "web_searcher.py"
REPORT_PATH = "research_report.md"

FOCUS_VARIANTS = (
    "prioritize source diversity and avoid repeating the same site category",
    "look for contrary evidence, caveats, and stale-data risks",
    "focus on concrete numbers, dates, ranges, and source limitations",
    "focus on what a user should verify next before acting",
)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    workspace_root = args.workspace_root.expanduser().resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)

    runs = []
    for index in range(1, args.runs + 1):
        run_id = f"run-{index:03d}"
        workspace = workspace_root / run_id
        task = _task_for_run(args.query, index=index, total=args.runs)
        command = _web_searcher_command(args, task=task, workspace=workspace, run_id=run_id)
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        run_summary = _summarize_run(workspace, run_id, result)
        runs.append(run_summary)
        print(_format_run_line(index, run_summary))
        if args.verbose and result.stdout:
            print(result.stdout.rstrip())
        if result.returncode != 0 and not args.continue_on_fail:
            break

    summary = {
        "query": args.query,
        "workspace_root": str(workspace_root),
        "config": {
            "runs": args.runs,
            "provider": args.provider,
            "web_backend": args.web_backend,
            "max_searches": args.max_searches,
            "target_fetches": args.target_fetches,
            "max_fetches": args.max_fetches,
            "compact_after_tool_steps": args.compact_after_tool_steps,
        },
        "aggregate": _aggregate(runs),
        "runs": runs,
    }
    summary_path = workspace_root / "multirun_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    status = "completed" if runs and all(run["status"] == "completed" for run in runs) and len(runs) == args.runs else "failed"
    print(f"multirun_status: {status}")
    print(f"summary: {summary_path}")
    return 0 if status == "completed" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run web_searcher.py multiple times for repeated and long-browse testing.")
    parser.add_argument("query")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--workspace-root", type=Path, default=Path("/tmp/tinyagent-web-multirun"))
    parser.add_argument("--provider", choices=["fake", "openai-compatible", "openai-responses", "openai-codex"], default="fake")
    parser.add_argument("--web-backend", choices=["fixture", "duckduckgo"], default="fixture")
    parser.add_argument("--base-url", default=os.environ.get("TINYAGENT_MODEL_BASE_URL", "http://127.0.0.1:8080/v1"))
    parser.add_argument("--api-key", default=os.environ.get("TINYAGENT_MODEL_API_KEY", "local"))
    parser.add_argument("--model", default=os.environ.get("TINYAGENT_MODEL_NAME"))
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("TINYAGENT_MODEL_TIMEOUT_SECONDS", "120")))
    parser.add_argument("--context-window", type=int, default=int(os.environ.get("TINYAGENT_MODEL_CONTEXT_WINDOW", "128000")))
    parser.add_argument("--max-output-tokens", type=int, default=int(os.environ.get("TINYAGENT_MODEL_MAX_OUTPUT_TOKENS", "8000")))
    parser.add_argument("--extra-body-json")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--web-timeout-seconds", type=int, default=20)
    parser.add_argument("--max-turns", type=int, default=14)
    parser.add_argument("--max-tool-calls", type=int, default=30)
    parser.add_argument("--max-run-seconds", type=int, default=300)
    parser.add_argument("--compact-after-tool-steps", type=int, default=4)
    parser.add_argument("--max-searches", type=int, default=1)
    parser.add_argument("--target-fetches", type=int, default=2)
    parser.add_argument("--max-fetches", type=int)
    parser.add_argument("--continue-on-fail", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def _web_searcher_command(args: argparse.Namespace, *, task: str, workspace: Path, run_id: str) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPT),
        task,
        "--provider",
        args.provider,
        "--web-backend",
        args.web_backend,
        "--workspace",
        str(workspace),
        "--run-id",
        run_id,
        "--base-url",
        args.base_url,
        "--api-key",
        args.api_key,
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--context-window",
        str(args.context_window),
        "--max-output-tokens",
        str(args.max_output_tokens),
        "--temperature",
        str(args.temperature),
        "--web-timeout-seconds",
        str(args.web_timeout_seconds),
        "--max-turns",
        str(args.max_turns),
        "--max-tool-calls",
        str(args.max_tool_calls),
        "--max-run-seconds",
        str(args.max_run_seconds),
        "--compact-after-tool-steps",
        str(args.compact_after_tool_steps),
        "--max-searches",
        str(args.max_searches),
        "--target-fetches",
        str(args.target_fetches),
    ]
    if args.model:
        command.extend(["--model", args.model])
    if args.extra_body_json:
        command.extend(["--extra-body-json", args.extra_body_json])
    if args.max_fetches is not None:
        command.extend(["--max-fetches", str(args.max_fetches)])
    return command


def _task_for_run(query: str, *, index: int, total: int) -> str:
    if total <= 1:
        return query
    focus = FOCUS_VARIANTS[(index - 1) % len(FOCUS_VARIANTS)]
    return f"{query}\n\nMultirun {index}/{total}: browse independently; {focus}."


def _summarize_run(workspace: Path, run_id: str, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    output_dir = workspace / ".tinyagent" / "runs" / run_id
    metrics = _read_json(output_dir / "metrics.json")
    events = _read_events(output_dir / "events.jsonl")
    report = workspace / REPORT_PATH
    status = str(metrics.get("status") or ("completed" if result.returncode == 0 else "failed"))
    return {
        "run_id": run_id,
        "status": status,
        "returncode": result.returncode,
        "workspace": str(workspace),
        "output_dir": str(output_dir),
        "report": str(report) if report.exists() else None,
        "report_chars": len(report.read_text(encoding="utf-8")) if report.exists() else 0,
        "model_calls": int(metrics.get("model_call_count") or 0),
        "tool_calls": int(metrics.get("tool_call_count") or 0),
        "compactions": int(metrics.get("compaction_count") or 0),
        "checkpoints": _event_count(events, "checkpoint.completed"),
        "web_search_calls": _tool_count(events, "web_search"),
        "fetch_url_calls": _tool_count(events, "fetch_url"),
        "max_context_tokens": _max_context_tokens(events),
        "duration_seconds": metrics.get("duration_seconds"),
        "failure_reason": metrics.get("failure_reason"),
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
    }


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "completed": sum(1 for run in runs if run["status"] == "completed"),
        "failed": sum(1 for run in runs if run["status"] != "completed"),
        "total_web_search_calls": sum(int(run["web_search_calls"]) for run in runs),
        "total_fetch_url_calls": sum(int(run["fetch_url_calls"]) for run in runs),
        "total_compactions": sum(int(run["compactions"]) for run in runs),
        "max_context_tokens": max((int(run["max_context_tokens"]) for run in runs), default=0),
    }


def _format_run_line(index: int, run: dict[str, Any]) -> str:
    return (
        f"run {index:03d}: status={run['status']} rc={run['returncode']} "
        f"searches={run['web_search_calls']} fetches={run['fetch_url_calls']} "
        f"checkpoints={run['checkpoints']} compactions={run['compactions']} "
        f"max_context_tokens={run['max_context_tokens']} report_chars={run['report_chars']}"
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _event_count(events: list[dict[str, Any]], event_type: str) -> int:
    return sum(1 for event in events if event.get("type") == event_type)


def _tool_count(events: list[dict[str, Any]], tool_name: str) -> int:
    return sum(
        1
        for event in events
        if event.get("type") == "tool.execution.completed" and event.get("data", {}).get("tool") == tool_name
    )


def _max_context_tokens(events: list[dict[str, Any]]) -> int:
    values = [
        int(event.get("data", {}).get("token_estimate") or 0)
        for event in events
        if event.get("type") == "context.built"
    ]
    return max(values, default=0)


def _tail(value: str, *, max_chars: int = 1_500) -> str:
    value = value.strip()
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


if __name__ == "__main__":
    raise SystemExit(main())
