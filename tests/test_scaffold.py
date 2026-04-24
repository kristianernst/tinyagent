from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_expected_top_level_scaffold_exists() -> None:
    expected_paths = [
        "agentd",
        "agentctl",
        "profiles",
        "profiles/apex-coder",
        "tests",
        "docs",
        "pyproject.toml",
    ]

    for path in expected_paths:
        assert (REPO_ROOT / path).exists(), path


def test_agentctl_console_script_is_declared() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()

    assert "[project.scripts]" in pyproject
    assert 'agentctl = "agentctl.cli:main"' in pyproject
