"""Event-derived metrics and regression thresholds for eval reports."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agentd.events import Event, load_events_jsonl


@dataclass(frozen=True)
class RunMetrics:
    context_token_estimate: int = 0
    tool_error_count: int = 0
    tool_error_kinds: dict[str, int] = field(default_factory=dict)
    policy_denials: int = 0
    sandbox_blocks: int = 0
    finish_gate_blocks: int = 0
    artifact_bytes_written: int = 0
    compaction_count: int = 0
    repeated_tool_call_count: int = 0

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_run_metrics(run_path: Path) -> RunMetrics:
    run_path = run_path.expanduser().resolve()
    events_path = run_path if run_path.name == "events.jsonl" else run_path / "events.jsonl"
    events = load_events_jsonl(events_path)
    tool_error_kinds: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    context_token_estimate = 0
    artifact_bytes = 0
    policy_denials = 0
    sandbox_blocks = 0
    finish_blocks = 0
    compactions = 0
    for event in events:
        if event.type == "context.built":
            context_token_estimate = int(event.data.get("token_estimate") or context_token_estimate)
        elif event.type in {"tool.execution.failed", "tool.execution.blocked", "tool.execution.cancelled"}:
            kind = _error_kind(event)
            tool_error_kinds[kind] += 1
            if kind == "policy_denied":
                policy_denials += 1
            if kind == "sandbox_blocked":
                sandbox_blocks += 1
        elif event.type == "policy.evaluated" and event.data.get("kind") == "deny":
            policy_denials += 1
        elif event.type == "finish.blocked":
            finish_blocks += 1
        elif event.type == "artifact.created":
            artifact_bytes += int(event.data.get("bytes") or 0)
        elif event.type == "contextfs.artifact.written":
            artifact_bytes += int(event.data.get("bytes") or 0)
        elif event.type == "checkpoint.completed":
            compactions = max(compactions, int(event.data.get("compaction_count") or compactions))
        elif event.type == "command.completed" or event.type == "command.failed":
            cmd = str(event.data.get("cmd") or "")
            if cmd:
                commands[cmd] += 1
    return RunMetrics(
        context_token_estimate=context_token_estimate,
        tool_error_count=sum(tool_error_kinds.values()),
        tool_error_kinds=dict(sorted(tool_error_kinds.items())),
        policy_denials=policy_denials,
        sandbox_blocks=sandbox_blocks,
        finish_gate_blocks=finish_blocks,
        artifact_bytes_written=artifact_bytes,
        compaction_count=compactions,
        repeated_tool_call_count=sum(count - 1 for count in commands.values() if count > 1),
    )


def evaluate_thresholds(results: list[dict[str, object]], threshold_path: Path) -> list[str]:
    config = json.loads(threshold_path.expanduser().read_text())
    failures: list[str] = []
    total = max(len(results), 1)
    successes = sum(1 for result in results if result.get("success"))
    solve_rate = successes / total
    min_solve_rate = config.get("min_solve_rate")
    if min_solve_rate is not None and solve_rate < float(min_solve_rate):
        failures.append(f"solve_rate {solve_rate:.3f} < {float(min_solve_rate):.3f}")
    max_policy_denials = config.get("max_policy_denials")
    if max_policy_denials is not None:
        value = sum(int(result.get("policy_denials") or 0) for result in results)
        if value > int(max_policy_denials):
            failures.append(f"policy_denials {value} > {int(max_policy_denials)}")
    max_unknown_errors = config.get("max_unknown_errors")
    if max_unknown_errors is not None:
        value = sum(int((result.get("tool_error_kinds") or {}).get("unknown", 0)) for result in results if isinstance(result.get("tool_error_kinds"), dict))
        if value > int(max_unknown_errors):
            failures.append(f"unknown_errors {value} > {int(max_unknown_errors)}")
    return failures


def _error_kind(event: Event) -> str:
    if event.type == "tool.execution.cancelled":
        return "user_aborted"
    data = event.data
    explicit = data.get("failure_kind")
    if isinstance(explicit, str) and explicit:
        return explicit
    nested = data.get("data")
    if isinstance(nested, dict):
        nested_kind = nested.get("failure_kind")
        if isinstance(nested_kind, str) and nested_kind:
            return nested_kind
        if nested.get("timeout"):
            return "timeout"
        if nested.get("blocked"):
            return "policy_denied"
    return "unknown"
