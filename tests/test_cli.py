from __future__ import annotations

import json
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest

import tinyagent.cli as cli
from tinyagent.cli import _sigint_cancel, main
from tinyagent.core.run_control import CancelToken


@pytest.fixture(autouse=True)
def isolated_tinyagent_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TINYAGENT_HOME", str(tmp_path / "home"))


def test_tinyagent_help_exits_successfully(capsys) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Control the tinyagent product." in captured.out
    assert "run" in captured.out
    assert "replay" in captured.out
    assert "serve" in captured.out


def test_tinyagent_serve_help_exits_successfully(capsys) -> None:
    try:
        main(["serve", "--help"])
    except SystemExit as exc:
        assert exc.code == 0

    captured = capsys.readouterr()

    assert "--workspace" in captured.out
    assert "--host" in captured.out
    assert "--port" in captured.out
    assert "--provider" in captured.out
    assert "--stream" in captured.out


def test_tinyagent_serve_uses_runtime_server_options(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TINYAGENT_HOME", str(home))
    calls = []

    class FakeServer:
        server_port = 9999

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            calls.append(("closed",))

    def fake_create_product_runtime_server(
        home_arg,
        *,
        host,
        port,
        provider,
        model_name,
        reasoning,
        stream,
        debug_level,
        workspace_mode,
        approval_mode,
        sandbox_mode,
        profile,
        profile_override,
        memory_enabled,
    ):
        calls.append(
            (
                Path(home_arg.root),
                host,
                port,
                provider,
                model_name,
                reasoning,
                stream,
                debug_level,
                workspace_mode,
                approval_mode,
                sandbox_mode,
                profile,
                profile_override,
                memory_enabled,
            )
        )
        return FakeServer()

    monkeypatch.setattr(cli, "create_product_runtime_server", fake_create_product_runtime_server)

    exit_code = main(
        [
            "serve",
            "--workspace",
            str(tmp_path),
            "--host",
            "127.0.0.2",
            "--port",
            "1234",
            "--provider",
            "fake",
            "--model",
            "fake-model",
            "--reasoning-json",
            '{"effort":"low"}',
            "--stream",
            "--debug",
            "1",
            "--workspace-mode",
            "current",
            "--approval-mode",
            "yolo",
            "--sandbox-mode",
            "none",
            "--profile",
            "tiny-pi",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 130
    assert "serving tinyagent runtime on http://127.0.0.2:9999" in captured.out
    assert list((home / "workspaces").glob("ws_*/workspace.json"))
    assert calls == [
        (
            home,
            "127.0.0.2",
            1234,
            "fake",
            "fake-model",
            {"effort": "low"},
            True,
            1,
            "current",
            "yolo",
            "none",
            "tiny-pi",
            True,
            False,
        ),
        ("closed",),
    ]


def test_tinyagent_serve_does_not_require_workspace(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TINYAGENT_HOME", str(home))
    calls = []

    class FakeServer:
        server_port = 8765

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            calls.append(("closed",))

    def fake_create_product_runtime_server(home_arg, **kwargs):
        calls.append((Path(home_arg.root), kwargs["provider"], kwargs["stream"]))
        return FakeServer()

    monkeypatch.setattr(cli, "create_product_runtime_server", fake_create_product_runtime_server)

    exit_code = cli.main(["serve", "--provider", "fake", "--stream"])
    captured = capsys.readouterr()

    assert exit_code == 130
    assert "serving tinyagent runtime on http://127.0.0.1:8765" in captured.out
    assert calls == [(home, "fake", True), ("closed",)]
    assert (home / "version.json").exists()
    assert not (home / "workspaces").exists()


def test_tinyagent_version_exits_successfully(capsys) -> None:
    try:
        main(["--version"])
    except SystemExit as exc:
        assert exc.code == 0

    captured = capsys.readouterr()

    assert "tinyagent 0.1.0" in captured.out


def test_tinyagent_config_path_creates_product_home(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("TINYAGENT_HOME", str(tmp_path / "home"))

    exit_code = cli.main(["config", "path"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == f"{tmp_path / 'home' / 'config.toml'}\n"
    assert (tmp_path / "home" / "version.json").exists()


def test_tinyagent_doctor_reports_ok_with_fake_provider(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("TINYAGENT_HOME", str(tmp_path / "home"))

    exit_code = cli.main(["doctor", "--workspace", str(tmp_path), "--provider", "fake", "--port", "0"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Tinyagent Doctor" in captured.out
    assert f"home: {tmp_path / 'home'}" in captured.out
    assert "config: ok" in captured.out
    assert "provider: ok (fake)" in captured.out
    assert "status: ok" in captured.out


def test_tinyagent_doctor_fails_for_missing_openai_compatible_env(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("TINYAGENT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("TINYAGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("TINYAGENT_MODEL_NAME", raising=False)

    exit_code = cli.main(
        ["doctor", "--workspace", str(tmp_path), "--provider", "openai-compatible", "--port", "0"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "provider api key: fail (TINYAGENT_MODEL_API_KEY)" in captured.out
    assert "provider model: fail (TINYAGENT_MODEL_NAME)" in captured.out
    assert "status: failed" in captured.out


def test_tinyagent_doctor_fails_when_port_is_unavailable(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("TINYAGENT_HOME", str(tmp_path / "home"))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

        exit_code = cli.main(["doctor", "--workspace", str(tmp_path), "--provider", "fake", "--port", str(port)])
        captured = capsys.readouterr()
    finally:
        sock.close()

    assert exit_code == 1
    assert f"port {port}: fail" in captured.out
    assert "status: failed" in captured.out


def test_tinyagent_doctor_reports_invalid_home_without_traceback(tmp_path, capsys, monkeypatch) -> None:
    bad_home = tmp_path / "home-file"
    bad_home.write_text("not a directory")
    monkeypatch.setenv("TINYAGENT_HOME", str(bad_home))

    exit_code = cli.main(["doctor", "--workspace", str(tmp_path), "--provider", "fake", "--port", "0"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "home writable: fail" in captured.out
    assert "version.json: fail" in captured.out
    assert "status: failed" in captured.out


def test_tinyagent_config_path_reports_invalid_home_without_traceback(tmp_path, capsys, monkeypatch) -> None:
    bad_home = tmp_path / "home-file"
    bad_home.write_text("not a directory")
    monkeypatch.setenv("TINYAGENT_HOME", str(bad_home))

    exit_code = cli.main(["config", "path"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out.startswith("config error: ")


def test_tinyagent_doctor_fails_for_corrupt_version_json(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "version.json").write_text("[]")
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    exit_code = cli.main(["doctor", "--workspace", str(tmp_path), "--provider", "fake", "--port", "0"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "version.json: fail" in captured.out
    assert "status: failed" in captured.out


def test_tinyagent_doctor_fails_for_invalid_port_range(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("TINYAGENT_HOME", str(tmp_path / "home"))

    exit_code = cli.main(["doctor", "--workspace", str(tmp_path), "--provider", "fake", "--port", "99999"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "port 99999: fail" in captured.out
    assert "status: failed" in captured.out


def test_tinyagent_run_fake_and_replay(tmp_path, capsys) -> None:
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

    replay_code = main(["replay", "run_cli"])
    replayed = capsys.readouterr()

    assert replay_code == 0
    assert "Tinyagent Replay" in replayed.out
    assert "run.started" in replayed.out
    assert "run.completed" in replayed.out

    inspect_code = main(["inspect", "run_cli"])
    inspected = capsys.readouterr()

    assert inspect_code == 0
    assert "Tinyagent Run Inspect" in inspected.out
    assert "run_id: run_cli" in inspected.out
    assert "status: completed" in inspected.out


def test_tinyagent_eval_fake_smoke_suite_passes(tmp_path, capsys) -> None:
    suite = Path(__file__).parents[1] / "evals" / "tiny"

    exit_code = main(["eval", str(suite), "--provider", "fake", "--output-dir", str(tmp_path / "eval-out")])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "cases: 3" in captured.out
    assert "successes: 3" in captured.out
    assert "solve_rate: 1.000" in captured.out


def test_tinyagent_run_creates_product_home(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    exit_code = cli.main(
        [
            "run",
            "answer",
            "--provider",
            "fake",
            "--workspace",
            str(workspace),
            "--run-id",
            "run_tinyagent_home",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "run_id: run_tinyagent_home" in captured.out
    assert (home / "version.json").exists()
    [workspace_record_path] = list((home / "workspaces").glob("ws_*/workspace.json"))
    workspace_id = json.loads(workspace_record_path.read_text())["workspace_id"]
    assert (home / "workspaces" / workspace_id / "runs" / "run_tinyagent_home" / "events.jsonl").exists()
    assert not (workspace / ".tinyagent" / "runs" / "run_tinyagent_home").exists()


def test_tinyagent_replay_and_inspect_resolve_home_run_ids(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    run_code = cli.main(
        [
            "run",
            "answer",
            "--provider",
            "fake",
            "--workspace",
            str(workspace),
            "--run-id",
            "run_home_lookup",
        ]
    )
    capsys.readouterr()
    assert run_code == 0

    replay_code = cli.main(["replay", "run_home_lookup"])
    replayed = capsys.readouterr()
    assert replay_code == 0
    assert "Tinyagent Replay" in replayed.out
    assert "run.started" in replayed.out

    inspect_code = cli.main(["inspect", "run_home_lookup"])
    inspected = capsys.readouterr()
    assert inspect_code == 0
    assert "Tinyagent Run Inspect" in inspected.out
    assert "run_id: run_home_lookup" in inspected.out


def test_tinyagent_run_rejects_path_like_home_run_id(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    exit_code = cli.main(["run", "answer", "--provider", "fake", "--workspace", str(workspace), "--run-id", "../escape"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == "workspace error: invalid run_id: ../escape\n"
    assert not (home / "workspaces").exists()


def test_tinyagent_init_registers_workspace_and_workspaces_commands(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    init_code = cli.main(["init", "--workspace", str(workspace), "--name", "Example", "--trust"])
    initialized = capsys.readouterr()

    assert init_code == 0
    assert "registered workspace" in initialized.out
    workspace_jsons = list((home / "workspaces").glob("ws_*/workspace.json"))
    assert len(workspace_jsons) == 1
    record = json.loads(workspace_jsons[0].read_text())
    workspace_id = record["workspace_id"]
    assert record["name"] == "Example"
    assert record["root"] == str(workspace.resolve())
    assert record["kind"] == "directory"
    assert record["trust"] == "trusted"
    list_code = cli.main(["workspaces", "list"])
    listed = capsys.readouterr()
    assert list_code == 0
    assert workspace_id in listed.out
    assert "Example" in listed.out

    show_code = cli.main(["workspaces", "show", workspace_id])
    shown = capsys.readouterr()
    assert show_code == 0
    assert json.loads(shown.out)["workspace_id"] == workspace_id

    remove_code = cli.main(["workspaces", "remove", workspace_id])
    removed = capsys.readouterr()
    assert remove_code == 0
    assert "removed: true" in removed.out
    assert cli.main(["workspaces", "list"]) == 0
    assert "No workspaces registered." in capsys.readouterr().out


def test_tinyagent_workspaces_remove_rejects_path_escape(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    outside = home / "outside"
    outside.mkdir(parents=True)
    outside_record = outside / "workspace.json"
    outside_record.write_text("{}")
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    exit_code = cli.main(["workspaces", "remove", "../outside"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "invalid workspace_id" in captured.out
    assert outside_record.exists()


def test_tinyagent_init_can_write_project_config(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    exit_code = cli.main(["init", "--workspace", str(workspace), "--project-config"])
    capsys.readouterr()

    assert exit_code == 0
    assert (workspace / ".tinyagent" / "config.toml").read_text() == "version = 1\n"


def test_tinyagent_run_uses_registered_default_provider_without_overwriting(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))
    monkeypatch.delenv("TINYAGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("TINYAGENT_MODEL_NAME", raising=False)

    assert cli.main(["init", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    [workspace_record_path] = list((home / "workspaces").glob("ws_*/workspace.json"))
    record = json.loads(workspace_record_path.read_text())
    record["default_provider"] = "openai-compatible"
    workspace_record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    exit_code = cli.main(["run", "answer", "--workspace", str(workspace)])
    captured = capsys.readouterr()
    updated = json.loads(workspace_record_path.read_text())

    assert exit_code == 1
    assert captured.out == "provider error: TINYAGENT_MODEL_API_KEY is required for openai-compatible provider.\n"
    assert updated["default_provider"] == "openai-compatible"


def test_tinyagent_run_uses_registered_default_profile_when_profile_omitted(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    assert cli.main(["init", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    [workspace_record_path] = list((home / "workspaces").glob("ws_*/workspace.json"))
    record = json.loads(workspace_record_path.read_text())
    record["default_profile"] = "tiny-pi"
    workspace_record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    exit_code = cli.main(["run", "answer", "--workspace", str(workspace), "--provider", "fake", "--run-id", "run_profile_default"])
    captured = capsys.readouterr()
    events = (next((home / "workspaces").glob("ws_*/runs/run_profile_default/events.jsonl"))).read_text().splitlines()
    started = next(json.loads(line) for line in events if json.loads(line)["type"] == "run.started")

    assert exit_code == 0
    assert "Fake run finished: answer" in captured.out
    assert started["data"]["profile"] == "tiny-pi"


def test_tinyagent_run_reports_unknown_profile_without_traceback(tmp_path, capsys) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    exit_code = cli.main(["run", "answer", "--workspace", str(workspace), "--provider", "fake", "--profile", "missing"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == "run error: Unknown profile: missing\n"


def test_tinyagent_run_explicit_provider_preserves_registered_default(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    assert cli.main(["init", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    [workspace_record_path] = list((home / "workspaces").glob("ws_*/workspace.json"))
    record = json.loads(workspace_record_path.read_text())
    record["default_provider"] = "openai-compatible"
    workspace_record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    exit_code = cli.main(
        ["run", "answer", "--workspace", str(workspace), "--provider", "fake", "--run-id", "run_explicit_provider"]
    )
    captured = capsys.readouterr()
    updated = json.loads(workspace_record_path.read_text())

    assert exit_code == 0
    assert "run_id: run_explicit_provider" in captured.out
    assert updated["default_provider"] == "openai-compatible"


def test_tinyagent_run_equals_form_provider_preserves_registered_default(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    assert cli.main(["init", "--workspace", str(workspace)]) == 0
    capsys.readouterr()
    [workspace_record_path] = list((home / "workspaces").glob("ws_*/workspace.json"))
    record = json.loads(workspace_record_path.read_text())
    record["default_provider"] = "openai-compatible"
    workspace_record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")

    exit_code = cli.main(
        ["run", "answer", "--workspace", str(workspace), "--provider=fake", "--run-id", "run_equals_provider"]
    )
    captured = capsys.readouterr()
    updated = json.loads(workspace_record_path.read_text())

    assert exit_code == 0
    assert "run_id: run_equals_provider" in captured.out
    assert updated["default_provider"] == "openai-compatible"


def test_tinyagent_run_from_git_subdir_uses_registered_git_root(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    nested = repo / "nested"
    nested.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    init_code = cli.main(["init", "--workspace", str(repo), "--name", "Repo"])
    capsys.readouterr()
    assert init_code == 0
    [workspace_record_path] = list((home / "workspaces").glob("ws_*/workspace.json"))

    run_code = cli.main(
        ["run", "answer", "--workspace", str(nested), "--provider", "fake", "--run-id", "run_git_root"]
    )
    captured = capsys.readouterr()
    record = json.loads(workspace_record_path.read_text())
    run_path = home / "workspaces" / record["workspace_id"] / "runs" / "run_git_root"
    metrics = json.loads((run_path / "metrics.json").read_text())

    assert run_code == 0
    assert "run_id: run_git_root" in captured.out
    assert record["root"] == str(repo.resolve())
    assert record["git_root"] == str(repo.resolve())
    assert metrics["original_workspace_root"] == str(repo.resolve())
    assert metrics["workspace_root"] == str(repo.resolve())
    assert not (repo / ".tinyagent" / "runs" / "run_git_root").exists()


def test_tinyagent_conversations_list_show_and_archive(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    run_code = cli.main(
        ["run", "hello", "--workspace", str(workspace), "--provider", "fake", "--run-id", "run_conversation_cli"]
    )
    run_output = capsys.readouterr().out
    assert run_code == 0
    conversation_id = next(line.split(": ", 1)[1] for line in run_output.splitlines() if line.startswith("conversation_id: "))
    [workspace_record_path] = list((home / "workspaces").glob("ws_*/workspace.json"))
    workspace_id = json.loads(workspace_record_path.read_text())["workspace_id"]
    conversations_root = home / "workspaces" / workspace_id / "conversations"
    conversation = conversations_root / conversation_id

    list_code = cli.main(["conversations", "--workspace", str(workspace), "list"])
    listed = capsys.readouterr()
    assert list_code == 0
    assert f"{conversation_id}\topen\t1\thello" in listed.out

    show_code = cli.main(["conversations", "--workspace", str(workspace), "show", conversation_id])
    shown = capsys.readouterr()
    assert show_code == 0
    shown_payload = json.loads(shown.out)
    assert shown_payload["conversation"]["conversation_id"] == conversation_id
    assert [turn["type"] for turn in shown_payload["turns"]] == ["turn.started", "turn.completed"]

    archive_code = cli.main(["conversations", "--workspace", str(workspace), "archive", conversation_id])
    archived = capsys.readouterr()
    assert archive_code == 0
    assert f"archived: {conversation_id}" in archived.out
    assert json.loads((conversation / "conversation.json").read_text())["status"] == "archived"


def test_tinyagent_serve_uses_product_conversation_root(tmp_path, capsys, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))
    calls = []

    class FakeServer:
        server_port = 8765

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            calls.append(("closed",))

    def fake_create_product_runtime_server(
        home_arg,
        *,
        host,
        port,
        provider,
        model_name,
        reasoning,
        stream,
        debug_level,
        workspace_mode,
        approval_mode,
        sandbox_mode,
        profile,
        profile_override,
        memory_enabled,
    ):
        calls.append(
            (
                Path(home_arg.root),
                provider,
                host,
                port,
                stream,
                debug_level,
                workspace_mode,
                approval_mode,
                sandbox_mode,
                profile,
                profile_override,
                memory_enabled,
            )
        )
        return FakeServer()

    monkeypatch.setattr(cli, "create_product_runtime_server", fake_create_product_runtime_server)

    exit_code = cli.main(["serve", "--workspace", str(workspace), "--provider", "fake"])
    capsys.readouterr()
    [workspace_record_path] = list((home / "workspaces").glob("ws_*/workspace.json"))
    workspace_id = json.loads(workspace_record_path.read_text())["workspace_id"]

    assert exit_code == 130
    assert (home / "workspaces" / workspace_id / "workspace.json").exists()
    assert calls == [
        (
            home,
            "fake",
            "127.0.0.1",
            8765,
            False,
            0,
            "current",
            "yolo",
            "none",
            "tiny-coder",
            False,
            False,
        ),
        ("closed",),
    ]


def test_tinyagent_run_fake_streams_text(tmp_path, capsys) -> None:
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


def test_tinyagent_run_jsonl_stream_respects_debug_level(tmp_path, capsys) -> None:
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


def test_tinyagent_run_rejects_invalid_debug_level(tmp_path, capsys) -> None:
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


def test_tinyagent_accepts_new_sandbox_mode_choices_and_reports_missing_backend(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("tinyagent.core.workspace.detect_container_backend", lambda: None)
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


def test_tinyagent_run_missing_workspace_fails_cleanly(tmp_path, capsys) -> None:
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
    assert captured.out == f"workspace error: Workspace does not exist or is not a directory: {missing.resolve()}\n"
    assert captured.err == ""


def test_tinyagent_eval_fake_suite_writes_results(tmp_path, capsys) -> None:
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


def test_tinyagent_run_openai_compatible_missing_env_fails_cleanly(tmp_path, capsys, monkeypatch) -> None:
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


def test_tinyagent_serve_openai_compatible_missing_env_fails_cleanly(tmp_path, capsys, monkeypatch) -> None:
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
