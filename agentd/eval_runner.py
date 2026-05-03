"""Tiny local eval runner for harness debugging."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentd.contracts import ModelProvider, PolicyEngine, Profile, Tool
from agentd.eval_metrics import evaluate_thresholds, extract_run_metrics
from agentd.events import EventSink
from agentd.kernel import Kernel
from agentd.run_control import CancelToken
from agentd.run_record import RunRecord, load_run_record
from agentd.state import ApprovalMode
from agentd.workspace import SandboxModeInput, WorkspaceMode

ModelFactory = Callable[[str], ModelProvider]


@dataclass(frozen=True)
class EvalCase:
    id: str
    task: str
    validation_command: str = ""
    timeout_seconds: int = 60
    setup_git: bool = True


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    run_id: str
    status: str
    success: bool
    validation_ok: bool
    validation_exit_code: int | None
    run_path: str
    workspace_path: str
    duration_seconds: float
    turn_count: int
    tool_call_count: int
    command_count: int
    patch_count: int
    final_diff_chars: int
    context_token_estimate: int = 0
    tool_error_count: int = 0
    tool_error_kinds: dict[str, int] | None = None
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
    harness_findings: list[str] | None = None
    failure_reason: str = ""
    validation_output_path: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvalRun:
    suite_path: Path
    output_dir: Path
    results: list[EvalResult]


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
    sandbox_mode: SandboxModeInput = "none",
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
            sandbox_mode=sandbox_mode,
        )
        results.append(result)
        if result.status == "cancelled":
            break
    _write_results(output_dir, suite_path=suite_path, results=results)
    return EvalRun(suite_path=suite_path, output_dir=output_dir, results=results)


def load_eval_cases(suite_path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for case_dir in sorted(path for path in suite_path.iterdir() if path.is_dir()):
        spec_path = case_dir / "task.json"
        if not spec_path.exists():
            continue
        spec = json.loads(spec_path.read_text())
        case_id = str(spec.get("id") or case_dir.name)
        task = str(spec["task"])
        cases.append(
            EvalCase(
                id=case_id,
                task=task,
                validation_command=str(spec.get("validation_command") or ""),
                timeout_seconds=int(spec.get("timeout_seconds") or 60),
                setup_git=bool(spec.get("setup_git", True)),
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
        f"policy_denials: {sum(result.policy_denials for result in eval_run.results)}",
        f"finish_gate_blocks: {sum(result.finish_gate_blocks for result in eval_run.results)}",
        f"progress_guard_interventions: {sum(result.progress_guard_interventions for result in eval_run.results)}",
        "",
        "| Case | Success | Run | Validation | Turns | Tools | Errors | Policy | Finish blocks | Diff chars |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in eval_run.results:
        lines.append(
            "| "
            f"{result.case_id} | {str(result.success).lower()} | {result.status} | "
            f"{str(result.validation_ok).lower()} | {result.turn_count} | {result.tool_call_count} | "
            f"{result.tool_error_count} | {result.policy_denials} | {result.finish_gate_blocks} | {result.final_diff_chars} |"
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
    failures = [result for result in eval_run.results if not result.success]
    if failures:
        lines.extend(["", "## Failures"])
        for result in failures:
            reason = result.failure_reason or f"validation exit {result.validation_exit_code}"
            lines.append(f"- {result.case_id}: {reason}")
    return "\n".join(lines) + "\n"


def check_eval_thresholds(eval_run: EvalRun, threshold_path: Path) -> list[str]:
    return evaluate_thresholds([result.to_json_dict() for result in eval_run.results], threshold_path)


def default_eval_output_dir(suite_path: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(".tinyagent") / "evals" / f"{suite_path.name}-{timestamp}"


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
    sandbox_mode: SandboxModeInput,
) -> EvalResult:
    case_dir = suite_path / case.id
    _prepare_workspace(case_dir, workspace_dir, setup_git=case.setup_git)
    kernel = Kernel(
        model=model_factory(case.task),
        profile=profile,
        tools=tools,
        policy=policy,
        stream=stream,
        event_sink=event_sink,
        workspace_mode=workspace_mode,
        approval_mode=approval_mode,
        sandbox_mode=sandbox_mode,
    )
    state = kernel.run(
        case.task,
        workspace=workspace_dir,
        run_id=case.id,
        output_dir=run_dir,
        cancel_token=cancel_token,
        workspace_mode=workspace_mode,
        approval_mode=approval_mode,
        sandbox_mode=sandbox_mode,
    )
    record = load_run_record(run_dir)
    metrics = extract_run_metrics(run_dir)
    validation_exit_code = None
    validation_ok = True
    validation_output_path = ""
    validation_workspace = state.workspace.root
    if case.validation_command and record.status == "completed":
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
) -> EvalResult:
    return EvalResult(
        case_id=case.id,
        run_id=record.run_id,
        status=record.status,
        success=success,
        validation_ok=validation_ok,
        validation_exit_code=validation_exit_code,
        run_path=record.run_path,
        workspace_path=str(workspace_dir),
        duration_seconds=record.duration_seconds,
        turn_count=record.turn_count,
        tool_call_count=record.tool_call_count,
        command_count=record.command_count,
        patch_count=record.patch_count,
        final_diff_chars=record.final_diff_chars,
        context_token_estimate=metrics.context_token_estimate,
        tool_error_count=metrics.tool_error_count,
        tool_error_kinds=metrics.tool_error_kinds,
        policy_denials=metrics.policy_denials,
        sandbox_blocks=metrics.sandbox_blocks,
        finish_gate_blocks=metrics.finish_gate_blocks,
        artifact_bytes_written=metrics.artifact_bytes_written,
        compaction_count=metrics.compaction_count,
        repeated_tool_call_count=metrics.repeated_tool_call_count,
        inspected_before_edit=metrics.inspected_before_edit,
        diff_after_edit=metrics.diff_after_edit,
        verification_after_edit=metrics.verification_after_edit,
        progress_guard_interventions=metrics.progress_guard_interventions,
        output_truncation_count=metrics.output_truncation_count,
        large_output_artifact_count=metrics.large_output_artifact_count,
        recent_tool_context_chars=metrics.recent_tool_context_chars,
        harness_findings=metrics.harness_findings,
        failure_reason=record.failure_reason,
        validation_output_path=validation_output_path,
    )


def _write_results(output_dir: Path, *, suite_path: Path, results: list[EvalResult]) -> None:
    (output_dir / "results.jsonl").write_text(
        "".join(json.dumps(result.to_json_dict(), sort_keys=True) + "\n" for result in results)
    )
    eval_run = EvalRun(suite_path=suite_path, output_dir=output_dir, results=results)
    (output_dir / "report.md").write_text(render_eval_report(eval_run))


def _combined_output(stdout: str, stderr: str) -> str:
    if stdout and stderr:
        return f"{stdout}\n{stderr}"
    return stdout or stderr
