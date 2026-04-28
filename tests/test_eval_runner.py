from __future__ import annotations

import json
import sys
from pathlib import Path

from agentd.eval_runner import load_eval_cases, render_eval_report, run_eval_suite
from agentd.models import FakeModelProvider
from agentd.policy import default_policy
from agentd.profiles import ApexCoderProfile
from agentd.run_record import load_run_record, render_run_inspection
from agentd.state import ModelResponse, ToolCall
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


def _fake_eval_responses(task: str) -> list[ModelResponse]:
    assert "hello.txt" in task
    return [
        ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "sed -n '1,120p' hello.txt"}),)),
        ModelResponse(content="done", finish_reason="stop"),
    ]
