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


def test_agentctl_run_fake_and_replay(tmp_path, capsys) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")

    exit_code = main(
        [
            "run",
            "read hello.txt and answer",
            "--provider",
            "fake",
            "--workspace",
            str(tmp_path),
            "--run-id",
            "run_cli",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "run_id: run_cli" in captured.out
    assert "Fake run finished after reading hello.txt." in captured.out

    replay_code = main(["replay", str(tmp_path / ".tinyagent" / "runs" / "run_cli")])
    replayed = capsys.readouterr()

    assert replay_code == 0
    assert "Tinyagent Replay" in replayed.out
    assert "run.started" in replayed.out
    assert "run.completed" in replayed.out


def test_agentctl_run_fake_streams_text(tmp_path, capsys) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")

    exit_code = main(
        [
            "run",
            "read hello.txt and answer",
            "--provider",
            "fake",
            "--workspace",
            str(tmp_path),
            "--run-id",
            "run_stream_cli",
            "--stream",
            "text",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Fake run finished after reading hello.txt." in captured.out
    assert "run_id: run_stream_cli" in captured.out
    assert captured.out.count("Fake run finished after reading hello.txt.") == 1


def test_agentctl_run_openai_compatible_missing_env_fails_cleanly(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("TINYAGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("TINYAGENT_MODEL_NAME", raising=False)

    exit_code = main(
        [
            "run",
            "answer",
            "--provider",
            "openai-compatible",
            "--workspace",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == "provider error: TINYAGENT_MODEL_API_KEY is required for openai-compatible provider.\n"
    assert captured.err == ""
