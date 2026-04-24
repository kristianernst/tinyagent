from __future__ import annotations

from agentctl.cli import main


def test_agentctl_help_exits_successfully(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Control the tinyagent harness." in captured.out
    assert "run" in captured.out
    assert "replay" in captured.out


def test_agentctl_version_exits_successfully(capsys) -> None:
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0

    captured = capsys.readouterr()

    assert "agentctl 0.1.0" in captured.out
