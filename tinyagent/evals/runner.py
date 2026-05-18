"""Tiny local eval runner for harness debugging."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tinyagent.core.auto_review import AutoReviewApprovalHandler
from tinyagent.core.config import RunConfig
from tinyagent.core.contracts import ModelProvider, PolicyEngine, Profile, Tool
from tinyagent.core.events import EventSink
from tinyagent.core.kernel import Kernel
from tinyagent.core.resources import LoadedResources
from tinyagent.core.run_control import CancelToken
from tinyagent.core.state import ApprovalMode, RunBudgets, SessionMode
from tinyagent.core.workspace import SandboxModeInput, WorkspaceMode
from tinyagent.evals.metrics import evaluate_thresholds, extract_run_metrics
from tinyagent.evals.variants import VariantSpec, validate_supported_eval_compare
from tinyagent.runtime.run_record import RunRecord, load_run_record

ModelFactory = Callable[[str], ModelProvider]
VariantModelFactory = Callable[[RunConfig, str], ModelProvider]
CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class EvalCase:
    id: str
    task: str
    validation_command: str = ""
    timeout_seconds: int = 60
    setup_git: bool = True
    budget_overrides: dict[str, int] = field(default_factory=dict)
    case_dir: Path = Path()


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    run_id: str
    provider: str
    model: str
    protocol: str
    adapter: str
    status: str
    success: bool
    validation_ok: bool
    validation_exit_code: int | None
    run_path: str
    workspace_path: str
    duration_seconds: float
    turn_count: int
    model_call_count: int
    tool_call_count: int
    command_count: int
    patch_count: int
    final_diff_tokens: int
    context_token_estimate: int = 0
    static_prompt_tokens: int = 0
    tool_schema_tokens: int = 0
    model_call_token_estimates: list[int] | None = None
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    profile_visible_tools: list[str] | None = None
    tool_error_count: int = 0
    tool_error_kinds: dict[str, int] | None = None
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
    invariant_failures: list[str] | None = None
    harness_findings: list[str] | None = None
    failure_reason: str = ""
    validation_output_path: str = ""
    validation_attempted: bool = False

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalRun:
    suite_path: Path
    output_dir: Path
    results: list[EvalResult]
    variant_name: str = ""
    variant_metadata: dict[str, Any] | None = None


def run_eval_suite(
    suite_path: Path,
    *,
    output_dir: Path,
    model_factory: ModelFactory,
    profile: Profile,
    tools: list[Tool],
    policy: PolicyEngine,
    stream: bool = False,
    event_sink: EventSink | None = None,
    cancel_token: CancelToken | None = None,
    workspace_mode: WorkspaceMode = "current",
    approval_mode: ApprovalMode = "yolo",
    session_mode: SessionMode = "normal",
    approvals_reviewer: str = "user",
    sandbox_mode: SandboxModeInput = "none",
    budgets: RunBudgets | None = None,
    variant_name: str = "",
    variant_metadata: dict[str, Any] | None = None,
    run_id_prefix: str = "",
    resources: LoadedResources | None = None,
) -> EvalRun:
    suite_path = suite_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    workspaces_dir = output_dir / "workspaces"
    runs_dir = output_dir / "runs"
    validation_dir = output_dir / "validation"
    for path in (workspaces_dir, runs_dir, validation_dir):
        path.mkdir(parents=True, exist_ok=True)

    results: list[EvalResult] = []
    for case in load_eval_cases(suite_path):
        if cancel_token is not None and cancel_token.cancelled:
            break
        result = _run_case(
            case,
            suite_path=suite_path,
            workspace_dir=workspaces_dir / case.id,
            run_dir=runs_dir / case.id,
            validation_dir=validation_dir,
            model_factory=model_factory,
            profile=profile,
            tools=tools,
            policy=policy,
            stream=stream,
            event_sink=event_sink,
            cancel_token=cancel_token,
            workspace_mode=workspace_mode,
            approval_mode=approval_mode,
            session_mode=session_mode,
            approvals_reviewer=approvals_reviewer,
            sandbox_mode=sandbox_mode,
            budgets=budgets,
            run_id_prefix=run_id_prefix,
            resources=resources,
        )
        results.append(result)
        if result.status == "cancelled":
            break
    _write_results(output_dir, suite_path=suite_path, results=results, variant_name=variant_name, variant_metadata=variant_metadata)
    return EvalRun(
        suite_path=suite_path,
        output_dir=output_dir,
        results=results,
        variant_name=variant_name,
        variant_metadata=variant_metadata,
    )


def load_eval_cases(suite_path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    for case_dir in sorted(path for path in suite_path.iterdir() if path.is_dir()):
        spec_path = case_dir / "task.json"
        if not spec_path.exists():
            continue
        spec = json.loads(spec_path.read_text())
        case_id = str(spec.get("id") or case_dir.name)
        if not CASE_ID_PATTERN.fullmatch(case_id):
            raise ValueError(f"Invalid eval case id: {case_id}")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate eval case id: {case_id}")
        seen_ids.add(case_id)
        task = str(spec["task"])
        cases.append(
            EvalCase(
                id=case_id,
                task=task,
                validation_command=str(spec.get("validation_command") or ""),
                timeout_seconds=int(spec.get("timeout_seconds") or 60),
                setup_git=bool(spec.get("setup_git", True)),
                budget_overrides=_budget_overrides(spec.get("budgets") or {}),
                case_dir=case_dir,
            )
        )
    if not cases:
        raise ValueError(f"No eval cases found in {suite_path}")
    return cases


def render_eval_report(eval_run: EvalRun) -> str:
    total = len(eval_run.results)
    passed = sum(1 for result in eval_run.results if result.success)
    lines = [
        "# Tinyagent Eval Report",
        "",
        f"suite: {eval_run.suite_path}",
        f"output_dir: {eval_run.output_dir}",
        f"cases: {total}",
        f"successes: {passed}",
        f"solve_rate: {passed / total if total else 0:.3f}",
        f"tool_errors: {sum(result.tool_error_count for result in eval_run.results)}",
        f"invariant_failures: {sum(result.invariant_failure_count for result in eval_run.results)}",
        f"policy_denials: {sum(result.policy_denials for result in eval_run.results)}",
        f"finish_gate_blocks: {sum(result.finish_gate_blocks for result in eval_run.results)}",
        f"progress_guard_interventions: {sum(result.progress_guard_interventions for result in eval_run.results)}",
        "",
    ]
    if eval_run.variant_name or eval_run.variant_metadata:
        metadata = eval_run.variant_metadata or {}
        lines.extend(
            [
                f"variant: {eval_run.variant_name or metadata.get('name', '')}",
                f"config_hash: {metadata.get('config_hash', '')}",
                f"git_sha: {metadata.get('git_sha', '')}",
                f"branch: {metadata.get('branch', '')}",
                "",
            ]
        )
    lines.extend(
        [
            "| Case | Provider | Protocol | Success | Status | Validation | Model calls | Tools | Batches | "
            "Input tok | Cached tok | Output tok | Errors | Policy | Finish blocks | Diff tokens |",
            "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for result in eval_run.results:
        lines.append(
            "| "
            f"{result.case_id} | {result.provider} | {result.protocol} | {str(result.success).lower()} | {result.status} | "
            f"{str(result.validation_ok).lower()} | {result.model_call_count} | {result.tool_call_count} | "
            f"{result.parallel_batch_count} | {result.input_tokens} | {result.cached_input_tokens} | {result.output_tokens} | "
            f"{result.tool_error_count} | {result.policy_denials} | {result.finish_gate_blocks} | {result.final_diff_tokens} |"
        )
    error_counts: dict[str, int] = {}
    for result in eval_run.results:
        for kind, count in (result.tool_error_kinds or {}).items():
            error_counts[kind] = error_counts.get(kind, 0) + count
    if error_counts:
        lines.extend(["", "## Error Kinds"])
        for kind, count in sorted(error_counts.items()):
            lines.append(f"- {kind}: {count}")
    finding_counts: dict[str, int] = {}
    for result in eval_run.results:
        for finding in result.harness_findings or []:
            finding_counts[finding] = finding_counts.get(finding, 0) + 1
    if finding_counts:
        lines.extend(["", "## Harness Findings"])
        for finding, count in sorted(finding_counts.items()):
            lines.append(f"- {finding}: {count}")
    invariant_counts: dict[str, int] = {}
    for result in eval_run.results:
        for failure in result.invariant_failures or []:
            invariant_counts[failure] = invariant_counts.get(failure, 0) + 1
    if invariant_counts:
        lines.extend(["", "## Invariant Failures"])
        for failure, count in sorted(invariant_counts.items()):
            lines.append(f"- {failure}: {count}")
    diagnostics = _diagnostic_totals(eval_run.results)
    if any(value for value in diagnostics.values()):
        lines.extend(["", "## Harness Diagnostics"])
        for key, value in diagnostics.items():
            if isinstance(value, float):
                if value:
                    lines.append(f"- {key}: {value:.3f}")
            elif value:
                lines.append(f"- {key}: {value}")
    mechanism_totals = _mechanism_totals(eval_run.results)
    if any(mechanism_totals.values()):
        lines.extend(["", "## Mechanism Metrics"])
        for key, value in mechanism_totals.items():
            if value:
                lines.append(f"- {key}: {value}")
    failures = [result for result in eval_run.results if not result.success]
    if failures:
        lines.extend(["", "## Failures"])
        for result in failures:
            reason = result.failure_reason or f"validation exit {result.validation_exit_code}"
            lines.append(f"- {result.case_id}: {reason}")
    return "\n".join(lines) + "\n"


def check_eval_thresholds(eval_run: EvalRun, threshold_path: Path) -> list[str]:
    return evaluate_thresholds([result.to_json_dict() for result in eval_run.results], threshold_path)


def check_eval_comparison_thresholds(comparison: EvalComparison, threshold_path: Path) -> list[str]:
    failures: list[str] = []
    for run in comparison.variants:
        for failure in check_eval_thresholds(run, threshold_path):
            failures.append(f"{run.variant_name}: {failure}")
    return failures


def default_eval_output_dir(suite_path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(".tinyagent") / "evals" / f"{suite_path.name}-{timestamp}"


@dataclass(frozen=True)
class EvalComparison:
    suite_path: Path
    output_dir: Path
    variants: list[EvalRun]


def run_eval_comparison(
    suite_path: Path,
    *,
    output_dir: Path,
    variants: list[VariantSpec],
    model_factory: VariantModelFactory,
    profile_factory: Callable[[RunConfig], Profile],
    tools_factory: Callable[[RunConfig], list[Tool]],
    policy_factory: Callable[[RunConfig], PolicyEngine],
    stream: bool = False,
    event_sink: EventSink | None = None,
    cancel_token: CancelToken | None = None,
    resources_factory: Callable[[RunConfig, Profile], LoadedResources | None] | None = None,
) -> EvalComparison:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    runs: list[EvalRun] = []
    seen_names: set[str] = set()
    for variant in variants:
        if cancel_token is not None and cancel_token.cancelled:
            break
        if variant.name in seen_names:
            raise ValueError(f"Duplicate eval variant name: {variant.name}")
        seen_names.add(variant.name)
        variant_dir = output_dir / variant.name
        config = variant.config
        validate_supported_eval_compare(config)
        suite_path_resolved = suite_path.expanduser().resolve()
        metadata = {
            **variant.metadata(),
            "suite_path": str(suite_path_resolved),
            "suite_hash": _suite_hash(suite_path_resolved),
        }
        profile = profile_factory(config)
        run = run_eval_suite(
            suite_path,
            output_dir=variant_dir,
            model_factory=lambda task, config=config: model_factory(config, task),
            profile=profile,
            tools=tools_factory(config),
            policy=policy_factory(config),
            stream=stream,
            event_sink=event_sink,
            cancel_token=cancel_token,
            workspace_mode=config.workspace_mode,  # type: ignore[arg-type]
            approval_mode=config.approval_mode,  # type: ignore[arg-type]
            approvals_reviewer=config.approvals_reviewer,
            sandbox_mode=config.sandbox_mode,  # type: ignore[arg-type]
            budgets=RunBudgets.from_mapping(config.budgets),
            variant_name=variant.name,
            variant_metadata=metadata,
            run_id_prefix=variant.name,
            resources=resources_factory(config, profile) if resources_factory is not None else None,
        )
        runs.append(run)
        if cancel_token is not None and cancel_token.cancelled:
            break
        if run.results and run.results[-1].status == "cancelled":
            break
    comparison = EvalComparison(suite_path=suite_path, output_dir=output_dir, variants=runs)
    _write_comparison(output_dir, comparison)
    return comparison


def render_eval_comparison(comparison: EvalComparison) -> str:
    lines = [
        "# Tinyagent Eval Comparison",
        "",
        f"suite: {comparison.suite_path}",
        f"output_dir: {comparison.output_dir}",
        "",
        "| Variant | Provider | Protocol | Solve rate | Validation rate | Model calls | Tools | Batches | "
        "Input tok | Cached tok | Output tok | Reason tok | Errors | Policy | Sandbox | Finish blocks | Compactions | Config | Git |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for run in comparison.variants:
        summary = _variant_summary(run)
        metadata = run.variant_metadata or {}
        lines.append(
            "| "
            f"{run.variant_name} | {summary['provider']} | {summary['protocol']} | "
            f"{summary['solve_rate']:.3f} | {summary['validation_rate']:.3f} | "
            f"{summary['model_calls']} | {summary['tool_calls']} | {summary['parallel_batches']} | "
            f"{summary['input_tokens']} | {summary['cached_input_tokens']} | {summary['output_tokens']} | "
            f"{summary['reasoning_tokens']} | {summary['tool_errors']} | {summary['policy_denials']} | "
            f"{summary['sandbox_blocks']} | {summary['finish_gate_blocks']} | {summary['compactions']} | "
            f"{metadata.get('config_hash', '')} | {str(metadata.get('git_sha', ''))[:12]} |"
        )
    lines.extend(
        [
            "",
            "## Profile Metrics",
            "",
            "| Variant | Profile | Visible tools | Solve | Validation | Static prompt tok | Tool schema tok | "
            "Context tok | Model calls | Tool calls | Repeated cmds | Diff after edit | Verification after edit | "
            "Finish blocks | Policy | Approvals | Invariants |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for run in comparison.variants:
        summary = _variant_summary(run)
        metadata = run.variant_metadata or {}
        config = metadata.get("config", {})
        profile = str(config.get("profile", "") or "tiny-coder") if isinstance(config, dict) else "tiny-coder"
        lines.append(
            "| "
            f"{run.variant_name} | {profile} | "
            f"{summary['visible_tool_count']} | "
            f"{summary['solve_rate']:.3f} | {summary['validation_rate']:.3f} | "
            f"{summary['static_prompt_tokens']} | {summary['tool_schema_tokens']} | {summary['context_token_estimate']} | "
            f"{summary['model_calls']} | {summary['tool_calls']} | {summary['repeated_tool_calls']} | "
            f"{summary['diff_after_edit']} | {summary['verification_after_edit']} | "
            f"{summary['finish_gate_blocks']} | {summary['policy_denials']} | {summary['approval_requests']} | "
            f"{summary['invariant_failures']} |"
        )
    diagnostics = _diagnostic_totals([result for run in comparison.variants for result in run.results])
    if any(value for value in diagnostics.values()):
        lines.extend(["", "## Trace Metrics"])
        for key, value in diagnostics.items():
            if isinstance(value, float):
                if value:
                    lines.append(f"- {key}: {value:.3f}")
            elif value:
                lines.append(f"- {key}: {value}")
    if len(comparison.variants) >= 2:
        base = _variant_summary(comparison.variants[0])
        lines.extend(["", "## Deltas"])
        for run in comparison.variants[1:]:
            current = _variant_summary(run)
            lines.append(
                f"- {run.variant_name}: solve_rate {current['solve_rate'] - base['solve_rate']:+.3f}, "
                f"tool_errors {current['tool_errors'] - base['tool_errors']:+d}, "
                f"tool_schema_tokens {current['tool_schema_tokens'] - base['tool_schema_tokens']:+d}, "
                f"visible_tools {current['visible_tool_count'] - base['visible_tool_count']:+d}, "
                f"finish_blocks {current['finish_gate_blocks'] - base['finish_gate_blocks']:+d}"
            )
    finding_counts: dict[str, int] = {}
    for run in comparison.variants:
        for result in run.results:
            for finding in result.harness_findings or []:
                finding_counts[finding] = finding_counts.get(finding, 0) + 1
    if finding_counts:
        lines.extend(["", "## Harness Categories"])
        for finding, count in sorted(finding_counts.items()):
            lines.append(f"- {finding}: {count}")
    mechanism_totals = _mechanism_totals([result for run in comparison.variants for result in run.results])
    if any(mechanism_totals.values()):
        lines.extend(["", "## Mechanism Metrics"])
        for key, value in mechanism_totals.items():
            if value:
                lines.append(f"- {key}: {value}")
    lines.extend(["", "## Metadata"])
    for run in comparison.variants:
        metadata = run.variant_metadata or {}
        config = metadata.get("config", {})
        lines.extend(
            [
                f"### {run.variant_name}",
                f"- provider: {config.get('provider', '')}",
                f"- observed_provider: {_variant_summary(run)['provider']}",
                f"- model: {config.get('model', '')}",
                f"- observed_model: {_variant_summary(run)['model']}",
                f"- protocol: {_variant_summary(run)['protocol']}",
                f"- adapter: {_variant_summary(run)['adapter']}",
                f"- profile: {config.get('profile', '')}",
                f"- profile_variant: {config.get('profile_variant', '')}",
                f"- context_policy: {config.get('context_policy', '')}",
                f"- tool_surface: {config.get('tool_surface', '')}",
                f"- effective_visible_tools: {', '.join(_variant_summary(run)['visible_tools'])}",
                f"- visible_tools: {', '.join(config.get('visible_tools', []) or [])}",
                f"- workspace_mode: {config.get('workspace_mode', '')}",
                f"- sandbox_mode: {config.get('sandbox_mode', '')}",
                f"- config_hash: {metadata.get('config_hash', '')}",
                f"- config_file_hash: {metadata.get('config_file_hash', '')}",
                f"- suite_hash: {metadata.get('suite_hash', '')}",
                f"- git_sha: {metadata.get('git_sha', '')}",
                f"- branch: {metadata.get('branch', '')}",
                f"- git_dirty: {str(metadata.get('git_dirty', False)).lower()}",
                f"- git_diff_hash: {metadata.get('git_diff_hash', '')}",
                f"- git_untracked_hash: {metadata.get('git_untracked_hash', '')}",
            ]
        )
    return "\n".join(lines) + "\n"


def _run_case(
    case: EvalCase,
    *,
    suite_path: Path,
    workspace_dir: Path,
    run_dir: Path,
    validation_dir: Path,
    model_factory: ModelFactory,
    profile: Profile,
    tools: list[Tool],
    policy: PolicyEngine,
    stream: bool,
    event_sink: EventSink | None,
    cancel_token: CancelToken | None,
    workspace_mode: WorkspaceMode,
    approval_mode: ApprovalMode,
    session_mode: SessionMode,
    approvals_reviewer: str,
    sandbox_mode: SandboxModeInput,
    budgets: RunBudgets | None,
    run_id_prefix: str,
    resources: LoadedResources | None,
) -> EvalResult:
    case_dir = case.case_dir or suite_path / case.id
    _prepare_workspace(case_dir, workspace_dir, setup_git=case.setup_git)
    model = model_factory(case.task)
    run_budgets = RunBudgets.from_mapping(case.budget_overrides, base=budgets)
    kernel = Kernel(
        model=model,
        profile=profile,
        tools=tools,
        policy=policy,
        budgets=run_budgets,
        approval_handler=AutoReviewApprovalHandler(model) if approvals_reviewer == "auto_review" else None,
        stream=stream,
        event_sink=event_sink,
        workspace_mode=workspace_mode,
        approval_mode=approval_mode,
        session_mode=session_mode,
        sandbox_mode=sandbox_mode,
        resources=resources,
    )
    run_id = f"{run_id_prefix}-{case.id}" if run_id_prefix else case.id
    state = kernel.run(
        case.task,
        workspace=workspace_dir,
        run_id=run_id,
        output_dir=run_dir,
        cancel_token=cancel_token,
        workspace_mode=workspace_mode,
        approval_mode=approval_mode,
        session_mode=session_mode,
        sandbox_mode=sandbox_mode,
    )
    record = load_run_record(run_dir)
    metrics = extract_run_metrics(run_dir)
    validation_exit_code = None
    validation_ok = not case.validation_command
    validation_attempted = False
    validation_output_path = ""
    validation_workspace = state.workspace.root
    if case.validation_command and record.status != "cancelled":
        validation_attempted = True
        validation_exit_code, validation_output_path = _run_validation(case, validation_workspace, validation_dir)
        validation_ok = validation_exit_code == 0
    elif case.validation_command:
        validation_ok = False
    success = record.status == "completed" and validation_ok
    return _result_from_record(
        case,
        record,
        metrics=metrics,
        workspace_dir=validation_workspace,
        success=success,
        validation_ok=validation_ok,
        validation_exit_code=validation_exit_code,
        validation_output_path=validation_output_path,
        validation_attempted=validation_attempted,
    )


def _prepare_workspace(case_dir: Path, workspace_dir: Path, *, setup_git: bool) -> None:
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    files_dir = case_dir / "files"
    if files_dir.exists():
        shutil.copytree(files_dir, workspace_dir)
    else:
        workspace_dir.mkdir(parents=True)
    if setup_git:
        subprocess.run(["git", "init"], cwd=workspace_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=workspace_dir, check=True, capture_output=True, text=True)
        subprocess.run(
            ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "init"],
            cwd=workspace_dir,
            check=True,
            capture_output=True,
            text=True,
        )


def _run_validation(case: EvalCase, workspace_dir: Path, validation_dir: Path) -> tuple[int, str]:
    output_path = validation_dir / f"{case.id}.txt"
    try:
        result = subprocess.run(
            case.validation_command,
            cwd=workspace_dir,
            shell=True,
            capture_output=True,
            text=True,
            timeout=case.timeout_seconds,
            check=False,
        )
        output = _combined_output(result.stdout, result.stderr) or f"validation exited {result.returncode}\n"
        output_path.write_text(output)
        return result.returncode, output_path.relative_to(validation_dir.parent).as_posix()
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        output_path.write_text(_combined_output(stdout, stderr) or f"validation timed out after {case.timeout_seconds}s\n")
        return 124, output_path.relative_to(validation_dir.parent).as_posix()


def _result_from_record(
    case: EvalCase,
    record: RunRecord,
    *,
    metrics,
    workspace_dir: Path,
    success: bool,
    validation_ok: bool,
    validation_exit_code: int | None,
    validation_output_path: str,
    validation_attempted: bool,
) -> EvalResult:
    return EvalResult(
        case_id=case.id,
        run_id=record.run_id,
        provider=metrics.provider,
        model=metrics.model,
        protocol=metrics.protocol,
        adapter=metrics.adapter,
        status=record.status,
        success=success,
        validation_ok=validation_ok,
        validation_exit_code=validation_exit_code,
        run_path=record.run_path,
        workspace_path=str(workspace_dir),
        duration_seconds=record.duration_seconds,
        turn_count=record.turn_count,
        model_call_count=record.model_call_count,
        tool_call_count=record.tool_call_count,
        command_count=record.command_count,
        patch_count=record.patch_count,
        final_diff_tokens=record.final_diff_tokens,
        context_token_estimate=metrics.context_token_estimate,
        static_prompt_tokens=metrics.static_prompt_tokens,
        tool_schema_tokens=metrics.tool_schema_tokens,
        model_call_token_estimates=metrics.model_call_token_estimates,
        input_tokens=metrics.input_tokens,
        cached_input_tokens=metrics.cached_input_tokens,
        cache_creation_input_tokens=metrics.cache_creation_input_tokens,
        output_tokens=metrics.output_tokens,
        reasoning_tokens=metrics.reasoning_tokens,
        total_tokens=metrics.total_tokens,
        profile_visible_tools=metrics.profile_visible_tools,
        tool_error_count=metrics.tool_error_count,
        tool_error_kinds=metrics.tool_error_kinds,
        unknown_tool_count=metrics.unknown_tool_count,
        invalid_tool_args_count=metrics.invalid_tool_args_count,
        policy_denials=metrics.policy_denials,
        sandbox_blocks=metrics.sandbox_blocks,
        finish_gate_blocks=metrics.finish_gate_blocks,
        approval_request_count=metrics.approval_request_count,
        hidden_artifact_fetch_failures=metrics.hidden_artifact_fetch_failures,
        artifact_bytes_written=metrics.artifact_bytes_written,
        compaction_count=metrics.compaction_count,
        parallel_batch_count=metrics.parallel_batch_count,
        batched_tool_call_count=metrics.batched_tool_call_count,
        repeated_tool_call_count=metrics.repeated_tool_call_count,
        time_to_first_tool_seconds=metrics.time_to_first_tool_seconds,
        time_to_first_edit_seconds=metrics.time_to_first_edit_seconds,
        inspected_before_edit=metrics.inspected_before_edit,
        diff_after_edit=metrics.diff_after_edit,
        verification_after_edit=metrics.verification_after_edit,
        progress_guard_interventions=metrics.progress_guard_interventions,
        output_truncation_count=metrics.output_truncation_count,
        large_output_artifact_count=metrics.large_output_artifact_count,
        recent_tool_context_tokens=metrics.recent_tool_context_tokens,
        context_search_count=metrics.context_search_count,
        context_read_count=metrics.context_read_count,
        search_code_count=metrics.search_code_count,
        skill_list_count=metrics.skill_list_count,
        skill_load_count=metrics.skill_load_count,
        mcp_search_count=metrics.mcp_search_count,
        mcp_load_count=metrics.mcp_load_count,
        mcp_call_count=metrics.mcp_call_count,
        invariant_failure_count=metrics.invariant_failure_count,
        invariant_failures=metrics.invariant_failures,
        harness_findings=metrics.harness_findings,
        failure_reason=record.failure_reason,
        validation_output_path=validation_output_path,
        validation_attempted=validation_attempted,
    )


def _write_results(
    output_dir: Path,
    *,
    suite_path: Path,
    results: list[EvalResult],
    variant_name: str = "",
    variant_metadata: dict[str, Any] | None = None,
) -> None:
    (output_dir / "results.jsonl").write_text("".join(json.dumps(result.to_json_dict(), sort_keys=True) + "\n" for result in results))
    if variant_metadata is not None:
        (output_dir / "variant.json").write_text(json.dumps(variant_metadata, indent=2, sort_keys=True) + "\n")
    eval_run = EvalRun(
        suite_path=suite_path,
        output_dir=output_dir,
        results=results,
        variant_name=variant_name,
        variant_metadata=variant_metadata,
    )
    (output_dir / "report.md").write_text(render_eval_report(eval_run))


def _write_comparison(output_dir: Path, comparison: EvalComparison) -> None:
    (output_dir / "comparison.md").write_text(render_eval_comparison(comparison))
    (output_dir / "comparison.json").write_text(
        json.dumps(
            {
                "suite_path": str(comparison.suite_path),
                "output_dir": str(comparison.output_dir),
                "variants": [
                    {
                        "name": run.variant_name,
                        "metadata": run.variant_metadata,
                        "summary": _variant_summary(run),
                    }
                    for run in comparison.variants
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _variant_summary(run: EvalRun) -> dict[str, Any]:
    total = len(run.results)
    successes = sum(1 for result in run.results if result.success)
    validation_attempts = sum(1 for result in run.results if result.validation_attempted)
    validations = sum(1 for result in run.results if result.validation_attempted and result.validation_ok)
    visible_tools = sorted({tool for result in run.results for tool in (result.profile_visible_tools or [])})
    providers = sorted({result.provider for result in run.results if result.provider})
    models = sorted({result.model for result in run.results if result.model})
    protocols = sorted({result.protocol for result in run.results if result.protocol})
    adapters = sorted({result.adapter for result in run.results if result.adapter})
    return {
        "cases": total,
        "provider": ",".join(providers),
        "model": ",".join(models),
        "protocol": ",".join(protocols),
        "adapter": ",".join(adapters),
        "successes": successes,
        "solve_rate": successes / total if total else 0.0,
        "validation_attempts": validation_attempts,
        "validation_rate": validations / validation_attempts if validation_attempts else 0.0,
        "visible_tools": visible_tools,
        "visible_tool_count": len(visible_tools),
        "model_calls": sum(result.model_call_count for result in run.results),
        "tool_calls": sum(result.tool_call_count for result in run.results),
        "parallel_batches": sum(result.parallel_batch_count for result in run.results),
        "batched_tool_calls": sum(result.batched_tool_call_count for result in run.results),
        "input_tokens": sum(result.input_tokens for result in run.results),
        "cached_input_tokens": sum(result.cached_input_tokens for result in run.results),
        "cache_creation_input_tokens": sum(result.cache_creation_input_tokens for result in run.results),
        "output_tokens": sum(result.output_tokens for result in run.results),
        "reasoning_tokens": sum(result.reasoning_tokens for result in run.results),
        "total_tokens": sum(result.total_tokens for result in run.results),
        "tool_errors": sum(result.tool_error_count for result in run.results),
        "unknown_tools": sum(result.unknown_tool_count for result in run.results),
        "invalid_tool_args": sum(result.invalid_tool_args_count for result in run.results),
        "policy_denials": sum(result.policy_denials for result in run.results),
        "approval_requests": sum(result.approval_request_count for result in run.results),
        "sandbox_blocks": sum(result.sandbox_blocks for result in run.results),
        "finish_gate_blocks": sum(result.finish_gate_blocks for result in run.results),
        "compactions": sum(result.compaction_count for result in run.results),
        "repeated_tool_calls": sum(result.repeated_tool_call_count for result in run.results),
        "static_prompt_tokens": max((result.static_prompt_tokens for result in run.results), default=0),
        "tool_schema_tokens": max((result.tool_schema_tokens for result in run.results), default=0),
        "context_token_estimate": max((result.context_token_estimate for result in run.results), default=0),
        "diff_after_edit": sum(1 for result in run.results if result.diff_after_edit),
        "verification_after_edit": sum(1 for result in run.results if result.verification_after_edit),
        "invariant_failures": sum(result.invariant_failure_count for result in run.results),
    }


def _mechanism_totals(results: list[EvalResult]) -> dict[str, int]:
    return {
        "context_search_count": sum(result.context_search_count for result in results),
        "context_read_count": sum(result.context_read_count for result in results),
        "search_code_count": sum(result.search_code_count for result in results),
        "skill_list_count": sum(result.skill_list_count for result in results),
        "skill_load_count": sum(result.skill_load_count for result in results),
        "mcp_search_count": sum(result.mcp_search_count for result in results),
        "mcp_load_count": sum(result.mcp_load_count for result in results),
        "mcp_call_count": sum(result.mcp_call_count for result in results),
    }


def _diagnostic_totals(results: list[EvalResult]) -> dict[str, int | float]:
    tool_latencies = [result.time_to_first_tool_seconds for result in results if result.time_to_first_tool_seconds]
    edit_latencies = [result.time_to_first_edit_seconds for result in results if result.time_to_first_edit_seconds]
    return {
        "invariant_failure_count": sum(result.invariant_failure_count for result in results),
        "repeated_tool_call_count": sum(result.repeated_tool_call_count for result in results),
        "unknown_tool_count": sum(result.unknown_tool_count for result in results),
        "invalid_tool_args_count": sum(result.invalid_tool_args_count for result in results),
        "approval_request_count": sum(result.approval_request_count for result in results),
        "output_truncation_count": sum(result.output_truncation_count for result in results),
        "large_output_artifact_count": sum(result.large_output_artifact_count for result in results),
        "hidden_artifact_fetch_failures": sum(result.hidden_artifact_fetch_failures for result in results),
        "max_context_token_estimate": max((result.context_token_estimate for result in results), default=0),
        "max_tool_schema_tokens": max((result.tool_schema_tokens for result in results), default=0),
        "avg_time_to_first_tool_seconds": sum(tool_latencies) / len(tool_latencies) if tool_latencies else 0.0,
        "avg_time_to_first_edit_seconds": sum(edit_latencies) / len(edit_latencies) if edit_latencies else 0.0,
    }


def _combined_output(stdout: str, stderr: str) -> str:
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr


def _budget_overrides(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ValueError("budgets must be an object")
    if not raw:
        return {}
    RunBudgets.from_mapping(raw)
    return dict(raw)


def _suite_hash(suite_path: Path) -> str:
    hasher = hashlib.sha256()
    for path in sorted(suite_path.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(suite_path).as_posix()
        hasher.update(relative.encode())
        hasher.update(b"\0")
        hasher.update(path.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()[:12]
