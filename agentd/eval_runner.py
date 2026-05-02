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
from agentd.events import EventSink
from agentd.kernel import Kernel
from agentd.run_control import CancelToken
from agentd.run_record import RunRecord, load_run_record
from agentd.state import ApprovalMode
from agentd.workspace import SandboxMode, WorkspaceMode

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
    sandbox_mode: SandboxMode = "none",
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
        "",
        "| Case | Success | Run | Validation | Turns | Tools | Commands | Patch | Diff chars |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for result in eval_run.results:
        lines.append(
            "| "
            f"{result.case_id} | {str(result.success).lower()} | {result.status} | "
            f"{str(result.validation_ok).lower()} | {result.turn_count} | {result.tool_call_count} | "
            f"{result.command_count} | {result.patch_count} | {result.final_diff_chars} |"
        )
    failures = [result for result in eval_run.results if not result.success]
    if failures:
        lines.extend(["", "## Failures"])
        for result in failures:
            reason = result.failure_reason or f"validation exit {result.validation_exit_code}"
            lines.append(f"- {result.case_id}: {reason}")
    return "\n".join(lines) + "\n"


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
    sandbox_mode: SandboxMode,
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
    kernel.run(
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
    validation_exit_code = None
    validation_ok = True
    validation_output_path = ""
    if case.validation_command and record.status == "completed":
        validation_exit_code, validation_output_path = _run_validation(case, workspace_dir, validation_dir)
        validation_ok = validation_exit_code == 0
    elif case.validation_command:
        validation_ok = False
    success = record.status == "completed" and validation_ok
    return _result_from_record(
        case,
        record,
        workspace_dir=workspace_dir,
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
