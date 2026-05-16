from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")

    tests = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    print(tests.stdout, end="")
    print(tests.stderr, end="", file=sys.stderr)
    if tests.returncode != 0:
        return tests.returncode

    from flowforge.parser import parse_backlog
    from flowforge.planner import plan_milestone

    items = parse_backlog((ROOT / "data" / "backlog.txt").read_text(encoding="utf-8"))
    plan = plan_milestone(items, capacity_by_owner={"ana": 4, "bo": 5, "cy": 3})
    assert [[item.key for item in wave.items] for wave in plan.waves] == [["FF-103", "FF-101", "FF-105"], ["FF-102"]]
    assert [item.key for item in plan.blocked] == ["FF-104"]

    cli_env = env | {"PYTHONPATH": str(ROOT / "src")}
    summary = _run([sys.executable, "-m", "flowforge.cli", "summary", "data/backlog.txt"], env=cli_env)
    assert "total_items: 6" in summary.stdout
    assert "blocked: 1" in summary.stdout

    plan_json = _run(
        [
            sys.executable,
            "-m",
            "flowforge.cli",
            "plan",
            "data/backlog.txt",
            "--capacity",
            "ana=4",
            "--capacity",
            "bo=5",
            "--capacity",
            "cy=3",
            "--format",
            "json",
        ],
        env=cli_env,
    )
    payload = json.loads(plan_json.stdout)
    assert payload["waves"][1]["items"][0]["key"] == "FF-102"

    with tempfile.TemporaryDirectory(prefix="flowforge-validate-") as tmp_dir:
        out_path = Path(tmp_dir) / "dist" / "milestone.md"
        _run(
            [
                sys.executable,
                "-m",
                "flowforge.cli",
                "export",
                "data/backlog.txt",
                "--format",
                "markdown",
                "--out",
                str(out_path),
                "--capacity",
                "ana=4",
                "--capacity",
                "bo=5",
                "--capacity",
                "cy=3",
            ],
            env=cli_env,
        )
        rendered = out_path.read_text(encoding="utf-8")
    assert "## Wave 1" in rendered
    assert "FF-104" in rendered

    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8").lower()
    assert "plan" in readme and "export" in readme
    assert "dependency-aware planner" in architecture
    return 0


def _run(args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        raise AssertionError(f"command failed ({result.returncode}): {' '.join(args)}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
