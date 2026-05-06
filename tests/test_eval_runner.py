from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from tinyagent.core.contracts import Tool
from tinyagent.core.config import VariantSpec
from tinyagent.evals.runner import load_eval_cases, render_eval_comparison, render_eval_report, run_eval_comparison, run_eval_suite
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import default_policy
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.run_control import CancelToken
from tinyagent.runtime.run_record import load_run_record, render_run_inspection
from tinyagent.core.state import Message, ModelResponse, PolicyDecision, RunState, ToolCall, ToolResult
from tinyagent.core.tools import default_tools


def test_run_record_inspects_completed_run(tmp_path) -> None:
    from tinyagent.core.kernel import Kernel

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


def test_eval_validation_runs_against_effective_worktree_workspace(tmp_path) -> None:
    suite = tmp_path / "suite"
    case = suite / "edit-file"
    files = case / "files"
    files.mkdir(parents=True)
    (files / "hello.txt").write_text("hello\n")
    validation = f"{sys.executable} -c \"from pathlib import Path; assert Path('hello.txt').read_text() == 'updated\\\\n'\""
    (case / "task.json").write_text(
        json.dumps(
            {
                "id": "edit-file",
                "task": "Edit hello.txt to say updated.",
                "validation_command": validation,
            }
        )
    )
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.txt",
            "@@",
            "-hello",
            "+updated",
            "*** End Patch",
        ]
    )
    output_dir = tmp_path / "eval-worktree"

    eval_run = run_eval_suite(
        suite,
        output_dir=output_dir,
        model_factory=lambda _task: FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff -- hello.txt"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=default_policy(),
        workspace_mode="worktree",
    )

    result = eval_run.results[0]
    assert result.success is True
    assert result.validation_ok is True
    assert Path(result.workspace_path) != output_dir / "workspaces" / "edit-file"
    assert result.diff_after_edit is True
    assert result.verification_after_edit is False
    assert "verification_after_edit_missing" in (result.harness_findings or [])
    assert "## Harness Findings" in (output_dir / "report.md").read_text()


def test_eval_comparison_runs_fake_variants_and_writes_metadata(tmp_path) -> None:
    suite = _write_suite(tmp_path)
    baseline = tmp_path / "baseline.toml"
    contextfs = tmp_path / "contextfs.toml"
    baseline.write_text('provider = "fake"\nmodel = "baseline"\nvisible_tools = ["read_file", "search_repo", "apply_patch", "shell"]\n')
    contextfs.write_text('provider = "fake"\nmodel = "contextfs"\nvisible_tools = ["read_file", "read_context", "search_repo", "apply_patch", "shell"]\n')
    output_dir = tmp_path / "compare-output"

    comparison = run_eval_comparison(
        suite,
        output_dir=output_dir,
        variants=[VariantSpec.parse(f"baseline={baseline}"), VariantSpec.parse(f"contextfs={contextfs}")],
        model_factory=lambda _config, task: FakeModelProvider(_fake_eval_responses(task)),
        profile_factory=lambda config: ApexCoderProfile(visible_tool_names=config.visible_tools or None),
        tools_factory=lambda _config: default_tools(),
        policy_factory=lambda _config: default_policy(),
    )
    report = render_eval_comparison(comparison)

    assert [run.variant_name for run in comparison.variants] == ["baseline", "contextfs"]
    assert "Tinyagent Eval Comparison" in report
    assert "config_hash" in report
    assert "visible_tools: read_file, read_context, search_repo, apply_patch, shell" in report
    assert comparison.variants[0].results[0].run_id == "baseline-read-file"
    assert (output_dir / "comparison.md").exists()
    assert (output_dir / "comparison.json").exists()
    variant_metadata = json.loads((output_dir / "baseline" / "variant.json").read_text())
    assert variant_metadata["suite_hash"]
    assert "git_dirty" in variant_metadata
    assert "git_untracked_hash" in variant_metadata


def test_eval_comparison_passes_model_config_to_variant_factory(tmp_path) -> None:
    suite = _write_suite(tmp_path)
    baseline = tmp_path / "baseline.toml"
    alternate = tmp_path / "alternate.toml"
    baseline.write_text('provider = "fake"\nmodel = "baseline"\n')
    alternate.write_text('provider = "fake"\nmodel = "alternate"\n')

    def model_for_config(config, task):
        if config.model == "alternate":
            return FakeModelProvider(_fake_eval_responses(task), model=config.model)
        bad_patch = "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: hello.txt",
                "@@",
                "-hello",
                "+bad",
                "*** End Patch",
            ]
        )
        return FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": bad_patch}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff -- hello.txt"}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ],
            model=config.model,
        )

    comparison = run_eval_comparison(
        suite,
        output_dir=tmp_path / "compare-models",
        variants=[VariantSpec.parse(f"baseline={baseline}"), VariantSpec.parse(f"alternate={alternate}")],
        model_factory=model_for_config,
        profile_factory=lambda config: ApexCoderProfile(visible_tool_names=config.visible_tools or None),
        tools_factory=lambda _config: default_tools(),
        policy_factory=lambda _config: default_policy(),
    )

    assert [run.results[0].success for run in comparison.variants] == [False, True]


def test_eval_compare_cli_runs_fake_variants(tmp_path, capsys) -> None:
    from tinyagent.cli import main

    suite = _write_suite(tmp_path)
    config = tmp_path / "variant.toml"
    config.write_text('provider = "fake"\nmodel = "fake-variant"\n')
    output_dir = tmp_path / "cli-compare"

    exit_code = main(["eval", "compare", str(suite), "--variant", f"fake={config}", "--output-dir", str(output_dir)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Tinyagent Eval Comparison" in captured.out
    assert "fake" in captured.out
    assert (output_dir / "comparison.md").exists()


def test_eval_compare_default_output_dir_preserves_timestamp(tmp_path) -> None:
    from tinyagent.cli import _default_eval_compare_output_dir

    suite = tmp_path / "suite"
    output_dir = _default_eval_compare_output_dir(suite)

    assert output_dir.name.startswith("suite-")
    assert output_dir.name.endswith("-compare")
    assert output_dir.parent == Path(".tinyagent") / "evals"


def test_eval_compare_cli_exits_nonzero_for_threshold_failure(tmp_path, capsys) -> None:
    from tinyagent.cli import main

    suite = _write_suite(tmp_path)
    config = tmp_path / "variant.toml"
    thresholds = tmp_path / "thresholds.json"
    config.write_text('provider = "fake"\n')
    thresholds.write_text(json.dumps({"min_solve_rate": 1.1}))

    exit_code = main(["eval", "compare", str(suite), "--variant", f"fake={config}", "--thresholds", str(thresholds)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "threshold failed: fake: solve_rate" in captured.out


def test_eval_compare_cli_returns_130_for_sigint_cancellation(tmp_path, monkeypatch) -> None:
    import tinyagent.cli as cli
    from tinyagent.evals.runner import EvalComparison

    suite = _write_suite(tmp_path)

    def cancel_comparison(suite_path, *, output_dir, variants, model_factory, profile_factory, tools_factory, policy_factory, cancel_token, **kwargs):
        del output_dir, variants, model_factory, profile_factory, tools_factory, policy_factory, kwargs
        cancel_token.cancel("sigint")
        return EvalComparison(suite_path=suite_path, output_dir=tmp_path / "cancelled", variants=[])

    monkeypatch.setattr(cli, "run_eval_comparison", cancel_comparison)

    assert cli.main(["eval", "compare", str(suite), "--variant", "fake"]) == 130


def test_eval_comparison_rejects_unsafe_variant_names(tmp_path) -> None:
    config = tmp_path / "variant.toml"
    config.write_text('provider = "fake"\n')

    try:
        VariantSpec.parse(f"../escape={config}")
    except ValueError as exc:
        assert "Variant names" in str(exc)
    else:
        raise AssertionError("expected unsafe variant name to be rejected")


def test_eval_comparison_rejects_unsupported_config_fields(tmp_path) -> None:
    suite = _write_suite(tmp_path)
    config = tmp_path / "variant.toml"
    config.write_text('provider = "fake"\n[context]\nmode = "full"\n')

    try:
        run_eval_comparison(
            suite,
            output_dir=tmp_path / "compare-output",
            variants=[VariantSpec.parse(f"bad={config}")],
            model_factory=lambda _config, task: FakeModelProvider(_fake_eval_responses(task)),
            profile_factory=lambda config: ApexCoderProfile(visible_tool_names=config.visible_tools or None),
            tools_factory=lambda _config: default_tools(),
            policy_factory=lambda _config: default_policy(),
        )
    except ValueError as exc:
        assert "Unsupported eval config fields: context" in str(exc)
    else:
        raise AssertionError("expected unsupported config field to be rejected")


def test_eval_comparison_rejects_unknown_config_fields(tmp_path) -> None:
    config = tmp_path / "variant.toml"
    config.write_text('provider = "fake"\ntypo = true\n')

    try:
        VariantSpec.parse(f"bad={config}")
    except ValueError as exc:
        assert "Unknown eval config fields: typo" in str(exc)
    else:
        raise AssertionError("expected unknown config field to be rejected")


def test_eval_config_rejects_invalid_visible_tools_type(tmp_path) -> None:
    config = tmp_path / "variant.toml"
    config.write_text('provider = "fake"\nvisible_tools = "read_file"\n')

    try:
        VariantSpec.parse(f"bad={config}")
    except ValueError as exc:
        assert "visible_tools must be a list of strings" in str(exc)
    else:
        raise AssertionError("expected invalid visible_tools type to be rejected")


def test_openai_compatible_compare_config_without_model_uses_environment(tmp_path, monkeypatch) -> None:
    from tinyagent.cli import _model_for

    config = tmp_path / "variant.toml"
    config.write_text('provider = "openai-compatible"\n')
    variant = VariantSpec.parse(f"openai={config}")
    monkeypatch.setenv("TINYAGENT_MODEL_API_KEY", "test-key")
    monkeypatch.setenv("TINYAGENT_MODEL_NAME", "env-model")

    provider = _model_for(variant.config.provider, "task", model_name=variant.config.model or None)

    assert variant.config.model == ""
    assert provider.config.model == "env-model"


def test_eval_comparison_rejects_on_request_approval_mode(tmp_path) -> None:
    suite = _write_suite(tmp_path)
    config = tmp_path / "variant.toml"
    config.write_text('provider = "fake"\napproval_mode = "on-request"\n')

    try:
        run_eval_comparison(
            suite,
            output_dir=tmp_path / "compare-output",
            variants=[VariantSpec.parse(f"bad={config}")],
            model_factory=lambda _config, task: FakeModelProvider(_fake_eval_responses(task)),
            profile_factory=lambda config: ApexCoderProfile(visible_tool_names=config.visible_tools or None),
            tools_factory=lambda _config: default_tools(),
            policy_factory=lambda _config: default_policy(),
        )
    except ValueError as exc:
        assert "approval_mode=on-request is not supported for eval compare" in str(exc)
    else:
        raise AssertionError("expected on-request approval mode to be rejected")


def test_eval_comparison_stops_after_cancelled_variant(tmp_path) -> None:
    suite = _write_cancelling_suite(tmp_path)
    token = CancelToken()

    comparison = run_eval_comparison(
        suite,
        output_dir=tmp_path / "compare-cancelled",
        variants=[VariantSpec.parse("first"), VariantSpec.parse("second")],
        model_factory=lambda _config, _task: FakeModelProvider([ModelResponse(tool_calls=(ToolCall(name="cancel"),))]),
        profile_factory=lambda _config: AllToolsProfile(),
        tools_factory=lambda _config: [CancellingTool()],
        policy_factory=lambda _config: AllowAllPolicy(),
        cancel_token=token,
    )

    assert [run.variant_name for run in comparison.variants] == ["first"]
    assert comparison.variants[0].results[0].status == "cancelled"


def test_eval_cases_reject_duplicate_and_unsafe_ids(tmp_path) -> None:
    suite = tmp_path / "suite"
    first = suite / "first"
    second = suite / "second"
    first.mkdir(parents=True)
    second.mkdir()
    (first / "task.json").write_text(json.dumps({"id": "dup", "task": "one"}))
    (second / "task.json").write_text(json.dumps({"id": "dup", "task": "two"}))

    try:
        load_eval_cases(suite)
    except ValueError as exc:
        assert "Duplicate eval case id: dup" in str(exc)
    else:
        raise AssertionError("expected duplicate eval case id to be rejected")

    (second / "task.json").write_text(json.dumps({"id": "../escape", "task": "two"}))
    try:
        load_eval_cases(suite)
    except ValueError as exc:
        assert "Invalid eval case id: ../escape" in str(exc)
    else:
        raise AssertionError("expected unsafe eval case id to be rejected")


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
