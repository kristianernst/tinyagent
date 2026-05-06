from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_expected_top_level_scaffold_exists() -> None:
    expected_paths = [
        "tinyagent",
        "tinyagent/cli.py",
        "profiles",
        "profiles/tiny-coder",
        "tests",
        "docs",
        "pyproject.toml",
    ]

    for path in expected_paths:
        assert (REPO_ROOT / path).exists(), path


def test_tinyagent_console_script_is_declared() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text()

    assert "[project.scripts]" in pyproject
    assert 'tinyagent = "tinyagent.cli:main"' in pyproject
