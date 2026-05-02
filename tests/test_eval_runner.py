from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from agentd.contracts import Tool
from agentd.eval_runner import load_eval_cases, render_eval_report, run_eval_suite
from agentd.models import FakeModelProvider
from agentd.policy import default_policy
from agentd.profiles import ApexCoderProfile
from agentd.run_control import CancelToken
from agentd.run_record import load_run_record, render_run_inspection
from agentd.state import Message, ModelResponse, PolicyDecision, RunState, ToolCall, ToolResult
from agentd.tools import default_tools


def test_run_record_inspects_completed_run(tmp_path) -> None:
    from agentd.kernel import Kernel

    hello = tmp_path / "hello.txt"
    hello.write_text("hello\n")
    model = FakeModelProvider(
        [
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "sed -n '1,120p' hello.txt"}),)),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    kernel = Kernel(model=model, profile=ApexCoderProfile(), tools=default_tools(), policy=default_policy())

    state = kernel.run("inspect hello.txt", workspace=tmp_path, run_id="inspect_run")
    record = load_run_record(state.output_dir)
    rendered = render_run_inspection(record)

    assert record.run_id == "inspect_run"
    assert record.status == "completed"
    assert record.command_count == 1
    assert record.model_calls[-1].response_artifact == "artifacts/model-response-0002.json"
    assert "Tinyagent Run Inspect" in rendered
    assert "commands: 1" in rendered
    assert "final_output: final.md" in rendered


def test_eval_suite_runs_cases_and_writes_report(tmp_path) -> None:
    suite = _write_suite(tmp_path)
    output_dir = tmp_path / "eval-output"

    eval_run = run_eval_suite(
        suite,
        output_dir=output_dir,
        model_factory=lambda task: FakeModelProvider(_fake_eval_responses(task)),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=default_policy(),
    )

    assert [case.id for case in load_eval_cases(suite)] == ["read-file"]
    assert len(eval_run.results) == 1
    assert eval_run.results[0].success is True
    assert eval_run.results[0].validation_ok is True
    assert (output_dir / "results.jsonl").exists()
    assert (output_dir / "report.md").exists()
    result = json.loads((output_dir / "results.jsonl").read_text().splitlines()[0])
    assert result["case_id"] == "read-file"
    assert "context-read" not in render_eval_report(eval_run)
    assert "read-file" in (output_dir / "report.md").read_text()


def test_eval_suite_stops_after_cancelled_case_and_skips_validation(tmp_path) -> None:
    suite = _write_cancelling_suite(tmp_path)
    output_dir = tmp_path / "eval-cancelled"
    token = CancelToken()

    eval_run = run_eval_suite(
        suite,
        output_dir=output_dir,
        model_factory=lambda _task: FakeModelProvider([ModelResponse(tool_calls=(ToolCall(name="cancel"),))]),
        profile=AllToolsProfile(),
        tools=[CancellingTool()],
        policy=AllowAllPolicy(),
        cancel_token=token,
    )

    assert [result.case_id for result in eval_run.results] == ["cancel-first"]
    result = eval_run.results[0]
    assert result.status == "cancelled"
    assert result.success is False
    assert result.validation_ok is False
    assert result.validation_exit_code is None
    assert result.validation_output_path == ""
    assert not (output_dir / "validation" / "cancel-first.txt").exists()
    assert not (output_dir / "workspaces" / "run-second").exists()


def _write_suite(tmp_path: Path) -> Path:
    suite = tmp_path / "suite"
    case = suite / "read-file"
    files = case / "files"
    files.mkdir(parents=True)
    (files / "hello.txt").write_text("hello\n")
    validation = f"{sys.executable} -c \"from pathlib import Path; assert Path('hello.txt').read_text() == 'hello\\\\n'\""
    (case / "task.json").write_text(
        json.dumps(
            {
                "id": "read-file",
                "task": "Inspect hello.txt and return done.",
                "validation_command": validation,
            }
        )
    )
    return suite


def _write_cancelling_suite(tmp_path: Path) -> Path:
    suite = tmp_path / "cancel-suite"
    first = suite / "cancel-first"
    first_files = first / "files"
    first_files.mkdir(parents=True)
    validation = f"{sys.executable} -c \"from pathlib import Path; Path('validated.txt').write_text('yes')\""
    (first / "task.json").write_text(
        json.dumps(
            {
                "id": "cancel-first",
                "task": "cancel",
                "validation_command": validation,
                "setup_git": False,
            }
        )
    )
    second = suite / "run-second"
    second_files = second / "files"
    second_files.mkdir(parents=True)
    (second / "task.json").write_text(
        json.dumps(
            {
                "id": "run-second",
                "task": "should not run",
                "setup_git": False,
            }
        )
    )
    return suite


def _fake_eval_responses(task: str) -> list[ModelResponse]:
    assert "hello.txt" in task
    return [
        ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "sed -n '1,120p' hello.txt"}),)),
        ModelResponse(content="done", finish_reason="stop"),
    ]


class AllToolsProfile:
    name = "all-tools"

    def system_prompt(self) -> str:
        return "test"

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return [Message(role="user", content=state.task)]

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        del state
        return list(all_tools.values())

    def should_continue(self, state: RunState) -> bool:
        del state
        return True

    def should_finish(self, state: RunState) -> bool:
        del state
        return False

    def should_compact(self, state: RunState) -> bool:
        del state
        return False

    def compact(self, state: RunState) -> None:
        del state


class CancellingTool:
    name = "cancel"
    schema = {"name": "cancel"}

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        state.request_cancel("eval cancellation")
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output="cancelled",
            ok=False,
            data={"cancelled": True, "reason": "eval cancellation"},
        )


class AllowAllPolicy:
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        del state
        return PolicyDecision.allow(f"{call.name} allowed")
