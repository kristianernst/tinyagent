from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / "examples").exists(), reason="examples directory is not present")


def run_web_searcher(task: str, workspace: Path, run_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples" / "web_searcher.py"),
            task,
            "--provider",
            "fake",
            "--web-backend",
            "fixture",
            "--workspace",
            str(workspace),
            "--run-id",
            run_id,
            "--compact-after-tool-steps",
            "3",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_web_searcher_stock_fixture_runs_end_to_end(tmp_path: Path) -> None:
    workspace = tmp_path / "web-stock"
    result = run_web_searcher("Do deep research on NVIDIA stock", workspace, "web-stock-fixture")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "status: completed" in result.stdout
    assert "provider: fake" in result.stdout
    assert "web_backend: fixture" in result.stdout
    assert "web_search_calls: 1" in result.stdout
    assert "fetch_url_calls: 2" in result.stdout
    assert "context_checkpoints: 1" in result.stdout
    report = (workspace / "research_report.md").read_text(encoding="utf-8")
    assert "NVIDIA Stock Research Fixture" in report
    assert "## Source Notes" in report
    assert "fixture://stocks/nvda-earnings" in report
    assert "fixture://stocks/nvda-risks" in report
    events = _events(workspace, "web-stock-fixture")
    assert any(event["type"] == "checkpoint.completed" for event in events)
    assert any(event["type"] == "model.tool_call.assembly.completed" and event["data"]["tool"] == "web_search" for event in events)
    assert any(event["type"] == "model.tool_call.assembly.completed" and event["data"]["tool"] == "write_report" for event in events)
    for request_text in _logical_request_texts(workspace, "web-stock-fixture"):
        assert "context_read(" not in request_text
        assert "context_search" not in request_text
        assert "contextfs:" not in request_text
        assert "Artifact:" not in request_text
        assert "context/" not in request_text
        assert "artifacts/" not in request_text
        assert "tail -120" not in request_text


def test_web_searcher_flight_fixture_runs_end_to_end(tmp_path: Path) -> None:
    workspace = tmp_path / "web-flight"
    result = run_web_searcher("Check flight prices from Copenhagen to Tokyo in August", workspace, "web-flight-fixture")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "status: completed" in result.stdout
    assert "web_search_calls: 1" in result.stdout
    assert "fetch_url_calls: 2" in result.stdout
    report = (workspace / "research_report.md").read_text(encoding="utf-8")
    assert "CPH to Tokyo Flight Research Fixture" in report
    assert "not a live fare quote" in report
    assert "fixture://flights/cph-tyo-fares" in report
    assert "fixture://flights/booking-patterns" in report


def test_web_searcher_multirun_fixture_summarizes_runs(tmp_path: Path) -> None:
    workspace_root = tmp_path / "web-multirun"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples" / "web_searcher_multirun.py"),
            "Check flight prices from Copenhagen to Tokyo in August",
            "--provider",
            "fake",
            "--web-backend",
            "fixture",
            "--workspace-root",
            str(workspace_root),
            "--runs",
            "2",
            "--compact-after-tool-steps",
            "3",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "multirun_status: completed" in result.stdout
    summary = json.loads((workspace_root / "multirun_summary.json").read_text(encoding="utf-8"))
    assert summary["aggregate"]["completed"] == 2
    assert summary["aggregate"]["total_web_search_calls"] == 2
    assert summary["aggregate"]["total_fetch_url_calls"] == 4
    assert all(run["status"] == "completed" for run in summary["runs"])


def test_web_research_profile_direct_context_uses_configured_tool_surface(tmp_path: Path) -> None:
    from examples.web_searcher import WebResearchProfile
    from tinyagent.core.contextfs import refresh_contextfs
    from tinyagent.core.state import RunState, Workspace

    state = RunState.create("direct web context", Workspace(tmp_path), run_id="direct-web-context")
    refresh_contextfs(state)

    built = WebResearchProfile().build_context(state)
    text = "\n".join(message.content for message in built.messages if isinstance(message.content, str))

    assert "context_read(" not in text
    assert "context_search" not in text
    assert "contextfs:" not in text
    assert "Artifact:" not in text
    assert "context/" not in text
    assert "artifacts/" not in text
    assert "tail -120" not in text


def test_coding_stress_suite_has_hard_prompt_and_seed_repo_fails_target_validation(tmp_path: Path) -> None:
    suite = ROOT / "examples" / "coding_stress" / "build-refactor-planner"
    task = json.loads((suite / "task.json").read_text(encoding="utf-8"))

    assert "docs/IMPLEMENTATION_BRIEF.md" in task["task"]
    assert "python3 scripts/validate.py" in task["task"]
    assert "git diff" in task["task"]
    assert task["budgets"]["max_model_calls"] == 35
    assert (suite / "files" / "docs" / "IMPLEMENTATION_BRIEF.md").exists()
    assert (suite / "files" / "tests" / "test_target_behavior.py").exists()

    workspace = tmp_path / "coding-stress-seed"
    shutil.copytree(suite / "files", workspace)
    result = subprocess.run(
        [sys.executable, "scripts/validate.py"],
        cwd=workspace,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "plan_milestone" in result.stderr + result.stdout
    assert not (workspace / "dist").exists()


def _events(workspace: Path, run_id: str) -> list[dict]:
    path = workspace / ".tinyagent" / "runs" / run_id / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _logical_request_texts(workspace: Path, run_id: str) -> list[str]:
    artifacts = workspace / ".tinyagent" / "runs" / run_id / "artifacts"
    texts: list[str] = []
    for request_path in sorted(artifacts.glob("model-request-logical-*.json")):
        request = json.loads(request_path.read_text(encoding="utf-8"))
        texts.append("\n".join(message["content"] for message in request["messages"] if isinstance(message.get("content"), str)))
    return texts
