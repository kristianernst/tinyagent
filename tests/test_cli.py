from __future__ import annotations

import json
import sys

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

    inspect_code = main(["inspect", str(tmp_path / ".tinyagent" / "runs" / "run_cli")])
    inspected = capsys.readouterr()

    assert inspect_code == 0
    assert "Tinyagent Run Inspect" in inspected.out
    assert "run_id: run_cli" in inspected.out
    assert "status: completed" in inspected.out


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


def test_agentctl_run_jsonl_stream_respects_debug_level(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "run",
            "answer",
            "--provider",
            "fake",
            "--workspace",
            str(tmp_path),
            "--run-id",
            "run_jsonl_debug",
            "--stream",
            "jsonl",
            "--debug",
            "0",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert '"type": "run.started"' in captured.out
    assert '"type": "model.text.delta"' in captured.out
    assert '"type": "artifact.created"' not in captured.out
    assert '"type": "model.completed"' not in captured.out


def test_agentctl_run_rejects_invalid_debug_level(tmp_path, capsys) -> None:
    exit_code = main(
        [
            "run",
            "answer",
            "--provider",
            "fake",
            "--workspace",
            str(tmp_path),
            "--debug",
            "-1",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == "debug error: --debug must be non-negative.\n"


def test_agentctl_eval_fake_suite_writes_results(tmp_path, capsys) -> None:
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
    output_dir = tmp_path / "eval-out"

    exit_code = main(["eval", str(suite), "--provider", "fake", "--output-dir", str(output_dir)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Tinyagent Eval Report" in captured.out
    assert "read-file" in captured.out
    assert (output_dir / "results.jsonl").exists()
    assert (output_dir / "report.md").exists()


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
