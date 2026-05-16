"""Event-derived metrics and regression thresholds for eval reports."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from tinyagent.core.events import Event, load_events_jsonl
from tinyagent.evals.invariants import check_event_invariants


@dataclass(frozen=True)
class RunMetrics:
    provider: str = ""
    model: str = ""
    protocol: str = ""
    adapter: str = ""
    context_token_estimate: int = 0
    static_prompt_tokens: int = 0
    tool_schema_tokens: int = 0
    model_call_token_estimates: list[int] = field(default_factory=list)
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    profile_visible_tools: list[str] = field(default_factory=list)
    tool_error_count: int = 0
    tool_error_kinds: dict[str, int] = field(default_factory=dict)
    unknown_tool_count: int = 0
    invalid_tool_args_count: int = 0
    policy_denials: int = 0
    sandbox_blocks: int = 0
    finish_gate_blocks: int = 0
    approval_request_count: int = 0
    hidden_artifact_fetch_failures: int = 0
    artifact_bytes_written: int = 0
    compaction_count: int = 0
    parallel_batch_count: int = 0
    batched_tool_call_count: int = 0
    repeated_tool_call_count: int = 0
    time_to_first_tool_seconds: float = 0.0
    time_to_first_edit_seconds: float = 0.0
    inspected_before_edit: bool = False
    diff_after_edit: bool = False
    verification_after_edit: bool = False
    progress_guard_interventions: int = 0
    output_truncation_count: int = 0
    large_output_artifact_count: int = 0
    recent_tool_context_tokens: int = 0
    context_search_count: int = 0
    context_read_count: int = 0
    search_code_count: int = 0
    skill_list_count: int = 0
    skill_load_count: int = 0
    mcp_search_count: int = 0
    mcp_load_count: int = 0
    mcp_call_count: int = 0
    invariant_failure_count: int = 0
    invariant_failures: list[str] = field(default_factory=list)
    harness_findings: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def extract_run_metrics(run_path: Path) -> RunMetrics:
    run_path = run_path.expanduser().resolve()
    events_path = run_path if run_path.name == "events.jsonl" else run_path / "events.jsonl"
    events = load_events_jsonl(events_path)
    invariant_failures = check_event_invariants(events)
    tool_error_kinds: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    context_token_estimate = 0
    static_prompt_tokens = 0
    tool_schema_tokens = 0
    model_call_token_estimates: list[int] = []
    pending_context_estimate: int | None = None
    provider = ""
    model = ""
    protocol = ""
    adapter = ""
    input_tokens = 0
    cached_input_tokens = 0
    cache_creation_input_tokens = 0
    output_tokens = 0
    reasoning_tokens = 0
    total_tokens = 0
    recent_tool_context_tokens = 0
    artifact_bytes = 0
    policy_denials = 0
    approval_requests = 0
    unknown_tool_count = 0
    invalid_tool_args_count = 0
    sandbox_blocks = 0
    finish_blocks = 0
    compactions = 0
    first_edit_seq: int | None = None
    first_edit_event: Event | None = None
    first_tool_event: Event | None = None
    first_edit_tool_call_id: str | None = None
    pre_edit_inspection = False
    diff_after_edit = False
    verification_after_edit = False
    progress_guard_interventions = 0
    truncations = 0
    large_outputs = 0
    parallel_batch_ids: set[str] = set()
    batched_tool_calls: set[str] = set()
    tool_counts: Counter[str] = Counter()
    profile_visible_tools: list[str] = []
    for event in events:
        if event.type == "run.started":
            provider = _event_str(event, "provider")
            model = _event_str(event, "model")
            protocol = _event_str(event, "protocol")
            adapter = _event_str(event, "adapter")
            visible = event.data.get("profile_visible_tools")
            if isinstance(visible, list):
                profile_visible_tools = [str(item) for item in visible if isinstance(item, str)]
        elif event.type == "model.usage":
            input_tokens += _event_int(event, "input_tokens")
            cached_input_tokens += _event_int(event, "cached_input_tokens")
            cache_creation_input_tokens += _event_int(event, "cache_creation_input_tokens")
            output_tokens += _event_int(event, "output_tokens")
            reasoning_tokens += _event_int(event, "reasoning_tokens")
            total_tokens += _event_int(event, "total_tokens")
        if event.type == "model.tool_call.assembly.completed":
            if first_tool_event is None:
                first_tool_event = event
            tool = str(event.data.get("tool") or "")
            if tool:
                tool_counts[tool] += 1
        elif event.type == "tool.execution.started":
            batch_id = event.data.get("batch_id")
            tool_call_id = event.data.get("tool_call_id")
            if isinstance(batch_id, str) and batch_id:
                parallel_batch_ids.add(batch_id)
                if isinstance(tool_call_id, str) and tool_call_id:
                    batched_tool_calls.add(tool_call_id)
        if event.type == "context.built":
            context_token_estimate = int(event.data.get("token_estimate") or context_token_estimate)
            pending_context_estimate = int(event.data.get("model_call_token_estimate") or context_token_estimate)
            static_prompt_tokens = max(static_prompt_tokens, _event_static_context_tokens(event))
            tool_schema_tokens = max(tool_schema_tokens, int(event.data.get("tool_schema_tokens") or 0))
            recent_tool_context_tokens = max(recent_tool_context_tokens, _event_tool_context_tokens(event))
        elif event.type == "model.call.started":
            if pending_context_estimate is not None:
                model_call_token_estimates.append(pending_context_estimate)
                pending_context_estimate = None
        elif event.type in {"tool.execution.completed", "tool.execution.failed", "tool.execution.blocked", "tool.execution.cancelled"}:
            if first_tool_event is None:
                first_tool_event = event
            if event.data.get("output_truncated"):
                truncations += 1
        if event.type in {"tool.execution.failed", "tool.execution.cancelled"}:
            kind = _error_kind(event)
            tool_error_kinds[kind] += 1
            if kind == "invalid_tool_args":
                invalid_tool_args_count += 1
            if _is_unknown_tool(event):
                unknown_tool_count += 1
            if kind == "sandbox_blocked":
                sandbox_blocks += 1
            if kind == "progress_blocked":
                progress_guard_interventions += 1
        elif event.type == "policy.evaluated" and event.data.get("kind") == "deny":
            policy_denials += 1
        elif event.type == "approval.requested":
            approval_requests += 1
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
            if _event_output_tokens(event) > 3_000:
                large_outputs += 1
        elif event.type in {"file.read", "search.completed", "code.search.completed"}:
            if first_edit_seq is None:
                pre_edit_inspection = True
        elif event.type == "tool.execution.output.snapshot":
            if _event_output_tokens(event) > 3_000:
                large_outputs += 1
        elif event.type == "patch.applied" and event.data.get("ok", True):
            if first_edit_seq is None:
                first_edit_seq = event.seq
                first_edit_event = event
                first_edit_tool_call_id = _tool_call_id(event)
        elif event.type == "workspace.mutation.detected":
            if first_edit_seq is None:
                first_edit_seq = event.seq
                first_edit_event = event
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
        provider=provider,
        model=model,
        protocol=protocol,
        adapter=adapter,
        context_token_estimate=context_token_estimate,
        static_prompt_tokens=static_prompt_tokens,
        tool_schema_tokens=tool_schema_tokens,
        model_call_token_estimates=model_call_token_estimates,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
        profile_visible_tools=profile_visible_tools,
        tool_error_count=sum(tool_error_kinds.values()),
        tool_error_kinds=dict(sorted(tool_error_kinds.items())),
        unknown_tool_count=unknown_tool_count,
        invalid_tool_args_count=invalid_tool_args_count,
        policy_denials=policy_denials,
        sandbox_blocks=sandbox_blocks,
        finish_gate_blocks=finish_blocks,
        approval_request_count=approval_requests,
        artifact_bytes_written=artifact_bytes,
        compaction_count=compactions,
        parallel_batch_count=len(parallel_batch_ids),
        batched_tool_call_count=len(batched_tool_calls),
        repeated_tool_call_count=sum(count - 1 for count in commands.values() if count > 1),
        time_to_first_tool_seconds=_elapsed_seconds(events, first_tool_event),
        time_to_first_edit_seconds=_elapsed_seconds(events, first_edit_event),
        inspected_before_edit=pre_edit_inspection,
        diff_after_edit=diff_after_edit,
        verification_after_edit=verification_after_edit,
        progress_guard_interventions=progress_guard_interventions,
        output_truncation_count=truncations,
        large_output_artifact_count=large_outputs,
        recent_tool_context_tokens=recent_tool_context_tokens,
        context_search_count=tool_counts["context_search"],
        context_read_count=tool_counts["context_read"],
        search_code_count=tool_counts["search_code"],
        skill_list_count=tool_counts["list_skills"],
        skill_load_count=tool_counts["load_skill"],
        mcp_search_count=tool_counts["mcp_search_tools"],
        mcp_load_count=tool_counts["mcp_load_tool"],
        mcp_call_count=tool_counts["mcp_call"],
        invariant_failure_count=len(invariant_failures),
        invariant_failures=invariant_failures,
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
    max_invariant_failures = config.get("max_invariant_failures")
    if max_invariant_failures is not None:
        value = sum(int(result.get("invariant_failure_count") or 0) for result in results)
        if value > int(max_invariant_failures):
            failures.append(f"invariant_failures {value} > {int(max_invariant_failures)}")
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


def _event_output_tokens(event: Event) -> int:
    output_tokens = event.data.get("output_tokens")
    return output_tokens if isinstance(output_tokens, int) else 0


def _event_int(event: Event, key: str) -> int:
    value = event.data.get(key)
    return value if isinstance(value, int) else 0


def _event_str(event: Event, key: str) -> str:
    value = event.data.get(key)
    return value if isinstance(value, str) else ""


def _event_static_context_tokens(event: Event) -> int:
    static_context_tokens = event.data.get("static_context_tokens")
    return static_context_tokens if isinstance(static_context_tokens, int) else 0


def _event_tool_context_tokens(event: Event) -> int:
    tool_context_tokens = event.data.get("tool_context_tokens")
    return tool_context_tokens if isinstance(tool_context_tokens, int) else 0


def _is_unknown_tool(event: Event) -> bool:
    data = event.data.get("data")
    if isinstance(data, dict) and data.get("error_type") == "UnknownTool":
        return True
    output = event.data.get("output")
    return isinstance(output, str) and output.startswith("Unknown tool requested:")


def _elapsed_seconds(events: list[Event], event: Event | None) -> float:
    if event is None:
        return 0.0
    start = next((item for item in events if item.type == "run.started"), events[0] if events else None)
    if start is None:
        return 0.0
    return max(0.0, _timestamp(event) - _timestamp(start))


def _timestamp(event: Event) -> float:
    value = event.time
    if isinstance(value, datetime):
        return value.timestamp()
    return 0.0


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
