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
    inspected_before_edit: bool = False
    diff_after_edit: bool = False
    verification_after_edit: bool = False
    progress_guard_interventions: int = 0
    output_truncation_count: int = 0
    large_output_artifact_count: int = 0
    recent_tool_context_chars: int = 0
    harness_findings: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_run_metrics(run_path: Path) -> RunMetrics:
    run_path = run_path.expanduser().resolve()
    events_path = run_path if run_path.name == "events.jsonl" else run_path / "events.jsonl"
    events = load_events_jsonl(events_path)
    tool_error_kinds: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    context_token_estimate = 0
    recent_tool_context_chars = 0
    artifact_bytes = 0
    policy_denials = 0
    sandbox_blocks = 0
    finish_blocks = 0
    compactions = 0
    first_edit_seq: int | None = None
    first_edit_tool_call_id: str | None = None
    pre_edit_inspection = False
    diff_after_edit = False
    verification_after_edit = False
    progress_guard_interventions = 0
    truncations = 0
    large_outputs = 0
    for event in events:
        if event.type == "context.built":
            context_token_estimate = int(event.data.get("token_estimate") or context_token_estimate)
            recent_tool_context_chars = int(event.data.get("tool_context_chars") or recent_tool_context_chars)
        elif event.type in {"tool.execution.completed", "tool.execution.failed", "tool.execution.blocked", "tool.execution.cancelled"}:
            if event.data.get("output_truncated"):
                truncations += 1
        if event.type in {"tool.execution.failed", "tool.execution.blocked", "tool.execution.cancelled"}:
            kind = _error_kind(event)
            tool_error_kinds[kind] += 1
            if kind == "sandbox_blocked":
                sandbox_blocks += 1
            if kind == "progress_blocked":
                progress_guard_interventions += 1
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
                if first_edit_seq is None and _is_inspection_command(cmd):
                    pre_edit_inspection = True
            if int(event.data.get("output_chars") or 0) > 12_000:
                large_outputs += 1
        elif event.type in {"file.read", "search.completed"}:
            if first_edit_seq is None:
                pre_edit_inspection = True
        elif event.type == "tool.execution.output.snapshot":
            if int(event.data.get("output_chars") or 0) > 12_000:
                large_outputs += 1
        elif event.type == "patch.applied" and event.data.get("ok", True):
            if first_edit_seq is None:
                first_edit_seq = event.seq
                first_edit_tool_call_id = _tool_call_id(event)
        elif event.type == "workspace.mutation.detected":
            if first_edit_seq is None:
                first_edit_seq = event.seq
                first_edit_tool_call_id = _tool_call_id(event)
        elif event.type == "observation.recorded":
            kind = str(event.data.get("kind") or "")
            if first_edit_seq is not None and event.seq > first_edit_seq:
                data = event.data.get("data", {})
                source = data.get("source") if isinstance(data, dict) else None
                observation_tool_call_id = data.get("tool_call_id") if isinstance(data, dict) else None
                is_separate_tool_step = first_edit_tool_call_id is None or observation_tool_call_id != first_edit_tool_call_id
                if kind == "diff_seen" and source != "workspace_delta" and is_separate_tool_step:
                    diff_after_edit = True
                if kind == "verification" and is_separate_tool_step:
                    verification_after_edit = True
            if kind == "policy_block" and event.data.get("data", {}).get("failure_kind") == "progress_blocked":
                progress_guard_interventions += 1
    findings = _harness_findings(
        first_edit_seq=first_edit_seq,
        inspected_before_edit=pre_edit_inspection,
        diff_after_edit=diff_after_edit,
        verification_after_edit=verification_after_edit,
        progress_guard_interventions=progress_guard_interventions,
        finish_blocks=finish_blocks,
    )
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
        inspected_before_edit=pre_edit_inspection,
        diff_after_edit=diff_after_edit,
        verification_after_edit=verification_after_edit,
        progress_guard_interventions=progress_guard_interventions,
        output_truncation_count=truncations,
        large_output_artifact_count=large_outputs,
        recent_tool_context_chars=recent_tool_context_chars,
        harness_findings=findings,
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
        value = sum(
            int((result.get("tool_error_kinds") or {}).get("unknown", 0))
            for result in results
            if isinstance(result.get("tool_error_kinds"), dict)
        )
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


def _tool_call_id(event: Event) -> str | None:
    value = event.data.get("tool_call_id")
    return value if isinstance(value, str) and value else None


def _is_inspection_command(command: str) -> bool:
    text = command.lower()
    return any(token in text for token in ("sed ", "cat ", "head ", "tail ", "rg ", "grep ", "git diff", "git show", "git status"))


def _harness_findings(
    *,
    first_edit_seq: int | None,
    inspected_before_edit: bool,
    diff_after_edit: bool,
    verification_after_edit: bool,
    progress_guard_interventions: int,
    finish_blocks: int,
) -> list[str]:
    findings: list[str] = []
    if first_edit_seq is not None and not inspected_before_edit:
        findings.append("inspected_before_edit_missing")
    if first_edit_seq is not None and not diff_after_edit:
        findings.append("diff_after_edit_missing")
    if first_edit_seq is not None and not verification_after_edit:
        findings.append("verification_after_edit_missing")
    if progress_guard_interventions:
        findings.append("progress_guard_intervened")
    if finish_blocks:
        findings.append("finish_gate_intervened")
    return findings
