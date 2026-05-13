from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / "examples").exists(), reason="examples directory is not present")


def run_example(script: str, workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "examples" / script), "--workspace", str(workspace)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_code_repair_flow_runs_end_to_end(tmp_path: Path) -> None:
    result = run_example("code_repair_flow.py", tmp_path / "code-repair")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "status: completed" in result.stdout
    assert "approved_commands: ['python -m pytest -q', 'python -m pytest -q']" in result.stdout
    assert "return a + b" in (tmp_path / "code-repair" / "calc.py").read_text(encoding="utf-8")


def test_research_review_flow_runs_end_to_end(tmp_path: Path) -> None:
    result = run_example("research_review_flow.py", tmp_path / "research-review")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "researcher_status: completed" in result.stdout
    assert "reviewer_status: completed" in result.stdout
    assert "Decision: accept." in (tmp_path / "research-review" / "review.md").read_text(encoding="utf-8")
