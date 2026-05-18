from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tinyagent.core.contracts import ProfileRuntimeCapabilities, Tool
from tinyagent.core.events import Event
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import default_policy
from tinyagent.core.profiles import ApexCoderProfile, profile_for
from tinyagent.core.resources import ResourceLoader
from tinyagent.core.run_control import CancelToken
from tinyagent.core.state import Message, ModelResponse, PolicyDecision, RunState, ToolCall, ToolResult, Workspace
from tinyagent.core.tools import default_tools
from tinyagent.evals.metrics import extract_run_metrics
from tinyagent.evals.runner import load_eval_cases, render_eval_comparison, render_eval_report, run_eval_comparison, run_eval_suite
from tinyagent.evals.variants import VariantSpec, validate_supported_eval_compare
from tinyagent.runtime.run_record import load_run_record, render_run_inspection


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
    assert result["provider"] == "fake"
    assert result["protocol"] == "openai_chat_completions"
    assert result["model_call_count"] == 2
    assert result["tool_schema_tokens"] > 0
    assert result["model_call_token_estimates"]
    assert result["invariant_failure_count"] == 0
    assert "context-read" not in render_eval_report(eval_run)
    report = (output_dir / "report.md").read_text()
    assert "read-file" in report
    assert "## Harness Diagnostics" in report


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


def test_eval_validation_runs_for_failed_non_cancelled_case(tmp_path) -> None:
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
                "budgets": {"max_model_calls": 1},
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
    output_dir = tmp_path / "eval-failed-but-valid"

    eval_run = run_eval_suite(
        suite,
        output_dir=output_dir,
        model_factory=lambda _task: FakeModelProvider([ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),))]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=default_policy(),
    )

    assert load_eval_cases(suite)[0].budget_overrides == {"max_model_calls": 1}
    result = eval_run.results[0]
    assert result.status == "failed"
    assert result.success is False
    assert result.validation_attempted is True
    assert result.validation_ok is True
    assert result.validation_exit_code == 0
    assert (output_dir / "validation" / "edit-file.txt").exists()


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


def test_eval_comparison_config_budgets_apply(tmp_path) -> None:
    suite = _write_suite(tmp_path)
    config = tmp_path / "variant.toml"
    config.write_text('provider = "fake"\n[budgets]\nmax_model_calls = 1\n')

    comparison = run_eval_comparison(
        suite,
        output_dir=tmp_path / "compare-budget",
        variants=[VariantSpec.parse(f"budgeted={config}")],
        model_factory=lambda _config, task: FakeModelProvider(_fake_eval_responses(task)),
        profile_factory=lambda config: profile_for(config.profile, visible_tool_names=config.visible_tools or None),
        tools_factory=lambda _config: default_tools(),
        policy_factory=lambda _config: default_policy(),
    )

    result = comparison.variants[0].results[0]
    assert result.status == "failed"
    assert result.validation_attempted is True
    assert result.validation_ok is True
    assert result.success is False
    assert result.failure_reason == "Run exceeded max_model_calls budget."


def test_eval_comparison_runs_fake_variants_and_writes_metadata(tmp_path) -> None:
    suite = _write_suite(tmp_path)
    baseline = tmp_path / "baseline.toml"
    contextfs = tmp_path / "contextfs.toml"
    baseline.write_text('provider = "fake"\nmodel = "baseline"\nvisible_tools = ["read_file", "search_code", "apply_patch", "shell"]\n')
    contextfs.write_text(
        'provider = "fake"\n'
        'model = "contextfs"\n'
        'visible_tools = ["read_file", "context_search", "context_read", "search_code", "apply_patch", "shell"]\n'
    )
    output_dir = tmp_path / "compare-output"

    comparison = run_eval_comparison(
        suite,
        output_dir=output_dir,
        variants=[VariantSpec.parse(f"baseline={baseline}"), VariantSpec.parse(f"contextfs={contextfs}")],
        model_factory=lambda _config, task: FakeModelProvider(_fake_eval_responses(task)),
        profile_factory=lambda config: profile_for(config.profile, visible_tool_names=config.visible_tools or None),
        tools_factory=lambda _config: default_tools(),
        policy_factory=lambda _config: default_policy(),
    )
    report = render_eval_comparison(comparison)

    assert [run.variant_name for run in comparison.variants] == ["baseline", "contextfs"]
    assert "Tinyagent Eval Comparison" in report
    assert "## Profile Metrics" in report
    assert "## Trace Metrics" in report
    assert "config_hash" in report
    assert "visible_tools: read_file, context_search, context_read, search_code, apply_patch, shell" in report
    assert comparison.variants[0].results[0].run_id == "baseline-read-file"
    assert (output_dir / "comparison.md").exists()
    assert (output_dir / "comparison.json").exists()
    variant_metadata = json.loads((output_dir / "baseline" / "variant.json").read_text())
    assert variant_metadata["suite_hash"]
    assert "git_dirty" in variant_metadata
    assert "git_untracked_hash" in variant_metadata
    comparison_json = json.loads((output_dir / "comparison.json").read_text())
    summaries = {variant["name"]: variant["summary"] for variant in comparison_json["variants"]}
    assert summaries["baseline"]["provider"] == "fake"
    assert summaries["baseline"]["protocol"] == "openai_chat_completions"
    assert summaries["contextfs"]["tool_schema_tokens"] > summaries["baseline"]["tool_schema_tokens"]
    assert summaries["contextfs"]["visible_tool_count"] > summaries["baseline"]["visible_tool_count"]


def test_eval_comparison_profiles_surface_context_deltas(tmp_path) -> None:
    suite = _write_suite(tmp_path)
    coder = tmp_path / "coder.toml"
    pi = tmp_path / "pi.toml"
    coder.write_text(
        'provider = "fake"\n'
        'model = "coder"\n'
        'profile = "tiny-coder"\n'
        'profile_variant = "default"\n'
        'context_policy = "dynamic-v1"\n'
        'tool_surface = "default"\n'
    )
    pi.write_text(
        'provider = "fake"\n'
        'model = "pi"\n'
        'profile = "tiny-pi"\n'
        'profile_variant = "minimal"\n'
        'context_policy = "pi-v1"\n'
        'tool_surface = "pi-minimal"\n'
    )
    output_dir = tmp_path / "compare-profiles"

    run_eval_comparison(
        suite,
        output_dir=output_dir,
        variants=[VariantSpec.parse(f"coder={coder}"), VariantSpec.parse(f"pi={pi}")],
        model_factory=lambda _config, task: FakeModelProvider(_fake_eval_responses(task)),
        profile_factory=lambda config: profile_for(config.profile, visible_tool_names=config.visible_tools or None),
        tools_factory=lambda _config: default_tools(),
        policy_factory=lambda _config: default_policy(),
        resources_factory=lambda _config, profile: ResourceLoader().load(
            suite,
            runtime_capabilities=profile.runtime_capabilities,
        ),
    )

    report = (output_dir / "comparison.md").read_text()
    comparison_json = json.loads((output_dir / "comparison.json").read_text())
    summaries = {variant["name"]: variant["summary"] for variant in comparison_json["variants"]}

    assert "## Profile Metrics" in report
    assert "| pi | tiny-pi |" in report
    assert summaries["coder"]["tool_schema_tokens"] > summaries["pi"]["tool_schema_tokens"]
    assert summaries["coder"]["visible_tool_count"] > summaries["pi"]["visible_tool_count"]
    assert summaries["pi"]["visible_tools"] == ["apply_patch", "read_file", "shell"]


def test_eval_comparison_can_run_tiny_pi_variant_with_resources(tmp_path) -> None:
    suite = _write_suite(tmp_path)
    pi = tmp_path / "pi.toml"
    pi.write_text(
        'provider = "fake"\n'
        'model = "pi"\n'
        'profile = "tiny-pi"\n'
        'profile_variant = "minimal"\n'
        'context_policy = "pi-v1"\n'
        'tool_surface = "pi-minimal"\n'
    )

    comparison = run_eval_comparison(
        suite,
        output_dir=tmp_path / "compare-pi",
        variants=[VariantSpec.parse(f"pi={pi}")],
        model_factory=lambda _config, task: FakeModelProvider(_fake_eval_responses(task)),
        profile_factory=lambda config: profile_for(config.profile, visible_tool_names=config.visible_tools or None),
        tools_factory=lambda _config: default_tools(),
        policy_factory=lambda _config: default_policy(),
        resources_factory=lambda _config, profile: ResourceLoader().load(
            suite,
            runtime_capabilities=profile.runtime_capabilities,
        ),
    )

    result = comparison.variants[0].results[0]
    events = [json.loads(line) for line in (Path(result.run_path) / "events.jsonl").read_text().splitlines() if line]
    started = next(event for event in events if event["type"] == "run.started")
    context = next(event for event in events if event["type"] == "context.built")

    assert started["data"]["profile"] == "tiny-pi"
    assert started["data"]["profile_visible_tools"] == ["read_file", "apply_patch", "shell"]
    assert context["data"]["visible_tools"] == ["read_file", "apply_patch", "shell"]
    assert result.context_search_count == 0
    assert result.search_code_count == 0
    assert "contextfs.index.updated" not in [event["type"] for event in events]


def test_eval_comparison_resource_factory_receives_resolved_profile(tmp_path) -> None:
    suite = _write_suite(tmp_path)
    seen: list[tuple[str, ProfileRuntimeCapabilities]] = []

    class LeanProfile(ApexCoderProfile):
        name = "lean-custom"
        runtime_capabilities = ProfileRuntimeCapabilities(skills=False, dynamic_context=False, extensions=False)

    comparison = run_eval_comparison(
        suite,
        output_dir=tmp_path / "compare-resolved-profile",
        variants=[VariantSpec.parse("custom")],
        model_factory=lambda _config, task: FakeModelProvider(_fake_eval_responses(task)),
        profile_factory=lambda _config: LeanProfile(visible_tool_names=("read_file", "shell")),
        tools_factory=lambda _config: default_tools(),
        policy_factory=lambda _config: default_policy(),
        resources_factory=lambda _config, profile: (
            seen.append((profile.name, profile.runtime_capabilities))
            or ResourceLoader().load(suite, runtime_capabilities=profile.runtime_capabilities)
        ),
    )

    assert comparison.variants[0].results[0].success is True
    assert seen == [("lean-custom", LeanProfile.runtime_capabilities)]


def test_eval_metrics_treat_code_search_as_pre_edit_inspection(tmp_path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    state = RunState.create("metrics", Workspace(tmp_path), run_id="run_metrics", output_dir=run)
    state.emit("code.search.completed", {"query": "needle", "refs": ["code:hello.py#L1"]})
    state.emit("patch.applied", {"ok": True, "paths": ["hello.py"], "tool_call_id": "call_patch"})

    metrics = extract_run_metrics(run)

    assert metrics.inspected_before_edit is True


def test_eval_metrics_time_to_first_tool_uses_model_tool_selection(tmp_path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    start = datetime(2026, 5, 8, tzinfo=UTC)
    events = [
        Event(type="run.started", run_id="run_metrics", seq=1, time=start),
        Event(
            type="model.call.started",
            run_id="run_metrics",
            seq=2,
            time=start + timedelta(seconds=0.5),
            data={"model_call_id": "model-call-1"},
        ),
        Event(
            type="model.tool_call.assembly.completed",
            run_id="run_metrics",
            seq=3,
            time=start + timedelta(seconds=1),
            data={"model_call_id": "model-call-1", "tool_call_id": "call-1", "tool": "shell"},
        ),
        Event(
            type="model.call.completed",
            run_id="run_metrics",
            seq=4,
            time=start + timedelta(seconds=1.1),
            data={"model_call_id": "model-call-1"},
        ),
        Event(
            type="policy.evaluated",
            run_id="run_metrics",
            seq=5,
            time=start + timedelta(seconds=1.2),
            data={"tool_call_id": "call-1", "kind": "allow"},
        ),
        Event(
            type="tool.execution.started",
            run_id="run_metrics",
            seq=6,
            time=start + timedelta(seconds=2),
            data={"tool_call_id": "call-1"},
        ),
        Event(
            type="tool.execution.completed",
            run_id="run_metrics",
            seq=7,
            time=start + timedelta(seconds=10),
            data={"tool_call_id": "call-1", "ok": True},
        ),
        Event(type="artifact.finalization.started", run_id="run_metrics", seq=8, time=start + timedelta(seconds=10.1)),
        Event(type="artifact.finalization.completed", run_id="run_metrics", seq=9, time=start + timedelta(seconds=10.2)),
        Event(type="run.completed", run_id="run_metrics", seq=10, time=start + timedelta(seconds=11)),
    ]
    (run / "events.jsonl").write_text("".join(json.dumps(event.to_json_dict(), sort_keys=True) + "\n" for event in events))

    metrics = extract_run_metrics(run)

    assert metrics.time_to_first_tool_seconds == 1.0


def test_eval_metrics_extract_provider_usage_and_parallel_batches(tmp_path) -> None:
    run = tmp_path / "run"
    run.mkdir()
    events = [
        Event(
            type="run.started",
            run_id="run_metrics",
            seq=1,
            data={
                "provider": "openai-responses",
                "model": "gpt-test",
                "protocol": "openai_responses",
                "adapter": "tinyagent.openai_responses.v1",
            },
        ),
        Event(
            type="model.usage",
            run_id="run_metrics",
            seq=2,
            data={
                "input_tokens": 10,
                "cached_input_tokens": 4,
                "cache_creation_input_tokens": 2,
                "output_tokens": 3,
                "reasoning_tokens": 1,
                "total_tokens": 14,
            },
        ),
        Event(
            type="model.usage",
            run_id="run_metrics",
            seq=3,
            data={"input_tokens": 5, "cached_input_tokens": 1, "output_tokens": 2, "total_tokens": 7},
        ),
        Event(
            type="tool.execution.started",
            run_id="run_metrics",
            seq=4,
            data={"tool_call_id": "call_a", "tool": "read_file", "batch_id": "batch_1"},
        ),
        Event(
            type="tool.execution.started",
            run_id="run_metrics",
            seq=5,
            data={"tool_call_id": "call_b", "tool": "read_file", "batch_id": "batch_1"},
        ),
        Event(type="run.completed", run_id="run_metrics", seq=6),
    ]
    (run / "events.jsonl").write_text("".join(json.dumps(event.to_json_dict(), sort_keys=True) + "\n" for event in events))

    metrics = extract_run_metrics(run)

    assert metrics.provider == "openai-responses"
    assert metrics.model == "gpt-test"
    assert metrics.protocol == "openai_responses"
    assert metrics.adapter == "tinyagent.openai_responses.v1"
    assert metrics.input_tokens == 15
    assert metrics.cached_input_tokens == 5
    assert metrics.cache_creation_input_tokens == 2
    assert metrics.output_tokens == 5
    assert metrics.reasoning_tokens == 1
    assert metrics.total_tokens == 21
    assert metrics.parallel_batch_count == 1
    assert metrics.batched_tool_call_count == 2


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
        profile_factory=lambda config: profile_for(config.profile, visible_tool_names=config.visible_tools or None),
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

    def cancel_comparison(
        suite_path,
        *,
        output_dir,
        variants,
        model_factory,
        profile_factory,
        tools_factory,
        policy_factory,
        cancel_token,
        **kwargs,
    ):
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
            profile_factory=lambda config: profile_for(config.profile, visible_tool_names=config.visible_tools or None),
            tools_factory=lambda _config: default_tools(),
            policy_factory=lambda _config: default_policy(),
        )
    except ValueError as exc:
        assert "Unsupported eval config fields: context" in str(exc)
    else:
        raise AssertionError("expected unsupported config field to be rejected")


def test_eval_config_accepts_default_profile_placeholders(tmp_path) -> None:
    config = tmp_path / "variant.toml"
    config.write_text(
        'provider = "fake"\nprofile = "tiny-coder"\nprofile_variant = "default"\ncontext_policy = "dynamic-v1"\ntool_surface = "default"\n'
    )

    variant = VariantSpec.parse(f"baseline={config}")
    validate_supported_eval_compare(variant.config)

    assert variant.config.profile_variant == "default"
    assert variant.config.context_policy == "dynamic-v1"
    assert variant.config.tool_surface == "default"


def test_eval_config_accepts_tiny_pi_profile_placeholders(tmp_path) -> None:
    config = tmp_path / "variant.toml"
    config.write_text(
        'provider = "fake"\nprofile = "tiny-pi"\nprofile_variant = "minimal"\ncontext_policy = "pi-v1"\ntool_surface = "pi-minimal"\n'
    )

    variant = VariantSpec.parse(f"pi={config}")
    validate_supported_eval_compare(variant.config)

    assert variant.config.profile == "tiny-pi"
    assert variant.config.profile_variant == "minimal"
    assert variant.config.context_policy == "pi-v1"
    assert variant.config.tool_surface == "pi-minimal"


def test_eval_config_rejects_unknown_profile_variant(tmp_path) -> None:
    config = tmp_path / "variant.toml"
    config.write_text('provider = "fake"\nprofile_variant = "claude-like"\n')
    variant = VariantSpec.parse(f"bad={config}")

    try:
        validate_supported_eval_compare(variant.config)
    except ValueError as exc:
        assert "Unsupported eval profile_variant: claude-like" in str(exc)
    else:
        raise AssertionError("expected unsupported profile variant to be rejected")


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
            profile_factory=lambda config: profile_for(config.profile, visible_tool_names=config.visible_tools or None),
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
