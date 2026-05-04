from __future__ import annotations

import json
import signal
import sys
from pathlib import Path

import agentctl.cli as cli
from agentctl.cli import _sigint_cancel, main
from agentd.run_control import CancelToken


def test_agentctl_help_exits_successfully(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Control the tinyagent harness." in captured.out
    assert "run" in captured.out
    assert "replay" in captured.out
    assert "serve" in captured.out


def test_agentctl_serve_help_exits_successfully(capsys) -> None:
    try:
        main(["serve", "--help"])
    except SystemExit as exc:
        assert exc.code == 0

    captured = capsys.readouterr()

    assert "--workspace" in captured.out
    assert "--host" in captured.out
    assert "--port" in captured.out
    assert "--run-root" in captured.out
    assert "--provider" in captured.out
    assert "--stream" in captured.out


def test_agentctl_serve_uses_runtime_server_options(tmp_path, capsys, monkeypatch) -> None:
    calls = []

    class FakeServer:
        server_port = 9999

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            calls.append(("closed",))

    def fake_create_runtime_server(
        workspace,
        *,
        host,
        port,
        run_root,
        provider,
        model_name,
        stream,
        debug_level,
        workspace_mode,
        approval_mode,
        sandbox_mode,
    ):
        calls.append(
            (
                Path(workspace),
                host,
                port,
                run_root,
                provider,
                model_name,
                stream,
                debug_level,
                workspace_mode,
                approval_mode,
                sandbox_mode,
            )
        )
        return FakeServer()

    monkeypatch.setattr(cli, "create_runtime_server", fake_create_runtime_server)

    exit_code = main(
        [
            "serve",
            "--workspace",
            str(tmp_path),
            "--host",
            "127.0.0.2",
            "--port",
            "1234",
            "--run-root",
            str(tmp_path / "runs"),
            "--provider",
            "fake",
            "--model",
            "fake-model",
            "--stream",
            "--debug",
            "1",
            "--workspace-mode",
            "current",
            "--approval-mode",
            "yolo",
            "--sandbox-mode",
            "none",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 130
    assert "serving tinyagent runtime on http://127.0.0.2:9999" in captured.out
    assert calls == [
        (tmp_path, "127.0.0.2", 1234, tmp_path / "runs", "fake", "fake-model", True, 1, "current", "yolo", "none"),
        ("closed",),
    ]


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


def test_agentctl_accepts_new_sandbox_mode_choices_and_reports_missing_backend(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("agentd.workspace.detect_container_backend", lambda: None)
    exit_code = main(
        [
            "run",
            "answer",
            "--provider",
            "fake",
            "--workspace",
            str(tmp_path),
            "--sandbox-mode",
            "container",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "sandbox-mode=container requires a usable Docker or Podman backend" in captured.out


def test_agentctl_run_missing_workspace_fails_cleanly(tmp_path, capsys) -> None:
    missing = tmp_path / "missing"

    exit_code = main(
        [
            "run",
            "answer",
            "--provider",
            "fake",
            "--workspace",
            str(missing),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == f"run error: Workspace does not exist or is not a directory: {missing.resolve()}\n"
    assert captured.err == ""


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


def test_agentctl_serve_openai_compatible_missing_env_fails_cleanly(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.delenv("TINYAGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("TINYAGENT_MODEL_NAME", raising=False)

    exit_code = main(
        [
            "serve",
            "--provider",
            "openai-compatible",
            "--workspace",
            str(tmp_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == "serve error: TINYAGENT_MODEL_API_KEY is required for openai-compatible provider.\n"
    assert captured.err == ""


def test_sigint_handler_sets_token_without_throwing_and_escalates() -> None:
    token = CancelToken()

    with _sigint_cancel(token):
        signal.raise_signal(signal.SIGINT)

    assert token.cancelled is True
    assert token.reason == "sigint"
    assert token.signal_count == 1
    assert token.escalated is False

    with _sigint_cancel(token):
        signal.raise_signal(signal.SIGINT)

    assert token.signal_count == 2
    assert token.escalated is True
