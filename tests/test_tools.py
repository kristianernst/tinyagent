from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time

import pytest

from agentd.kernel import Kernel
from agentd.models import FakeModelProvider
from agentd.output import capture_final_diff
from agentd.policy import LocalPolicy
from agentd.profiles import ApexCoderProfile
from agentd.replay import replay_run
from agentd.state import ModelResponse, RunBudgets, RunState, ToolCall, Workspace
from agentd.tools import (
    MAX_READ_FILE_BYTES,
    ApplyPatchTool,
    ListFilesTool,
    ReadFileTool,
    SearchRepoTool,
    ShellTool,
    _run_rg_limited,
    all_tools,
    apply_openai_patch,
    builtin_tools,
    default_tools,
    repo_inspect_tools,
)


def test_list_and_search_exclude_tinyagent_outputs(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("needle\n")
    trace_dir = tmp_path / ".tinyagent" / "runs" / "run_test"
    trace_dir.mkdir(parents=True)
    (trace_dir / "events.jsonl").write_text("needle\n")
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")

    listed = ListFilesTool().run(ToolCall(name="list_files"), state)
    searched = SearchRepoTool().run(ToolCall(name="search_repo", args={"query": "needle"}), state)

    assert listed.ok is True
    assert "hello.txt" in listed.output
    assert ".tinyagent" not in listed.output
    assert searched.ok is True
    assert "hello.txt" in searched.output
    assert ".tinyagent" not in searched.output
    assert [event.type for event in state.events] == ["FilesListed", "ArtifactWritten", "SearchCompleted"]


def test_read_file_and_apply_patch_protect_current_run_artifacts(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    state.output_dir.mkdir(parents=True)
    (state.output_dir / "events.jsonl").write_text("{}\n")

    read = ReadFileTool().run(ToolCall(name="read_file", args={"path": ".tinyagent/runs/run_test/events.jsonl"}), state)
    patch = ApplyPatchTool().run(
        ToolCall(
            name="apply_patch",
            args={
                "patch": "\n".join(
                    [
                        "*** Begin Patch",
                        "*** Add File: .tinyagent/runs/run_test/tamper.txt",
                        "+nope",
                        "*** End Patch",
                    ]
                )
            },
        ),
        state,
    )

    assert read.ok is False
    assert "current run artifacts" in read.output
    assert patch.ok is False
    assert "current run artifacts" in patch.output


def test_custom_output_dir_is_excluded_from_list_search_and_final_diff(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("tracked\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)

    output_dir = tmp_path / "run-output"
    output_dir.mkdir()
    (output_dir / "events.jsonl").write_text("needle from trace\n")
    (tmp_path / "real.txt").write_text("needle from workspace\n")
    state = RunState.create("test", Workspace(tmp_path), run_id="run_custom", output_dir=output_dir)

    listed = ListFilesTool().run(ToolCall(name="list_files"), state)
    searched = SearchRepoTool().run(ToolCall(name="search_repo", args={"query": "needle"}), state)
    listed_output_dir = ListFilesTool().run(ToolCall(name="list_files", args={"path": "run-output"}), state)
    searched_output_dir = SearchRepoTool().run(ToolCall(name="search_repo", args={"query": "needle", "path": "run-output"}), state)
    capture_final_diff(state)

    assert listed.ok is True
    assert searched.ok is True
    assert listed_output_dir.ok is True
    assert searched_output_dir.ok is True
    assert "real.txt" in listed.output
    assert "real.txt" in searched.output
    assert "run-output" not in listed.output
    assert "run-output" not in searched.output
    assert listed_output_dir.output == ""
    assert searched_output_dir.output == "No matches."
    assert "real.txt" in state.final_diff
    assert "run-output" not in state.final_diff


def test_local_policy_blocks_outside_paths_and_risky_shell(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    policy = LocalPolicy()

    outside = policy.evaluate(ToolCall(name="read_file", args={"path": "../secret.txt"}), state)
    shell = policy.evaluate(ToolCall(name="shell", args={"cmd": "rm -rf build"}), state)

    assert outside.allowed is False
    assert "outside workspace" in outside.reason
    assert shell.allowed is False
    assert "denied" in shell.reason


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf build",
        "rm -fr build",
        "rm -r -f build",
        "rm -f -r build",
        "rm --recursive --force build",
    ],
)
def test_local_policy_blocks_common_recursive_force_rm_variants(tmp_path, cmd) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    decision = LocalPolicy().evaluate(ToolCall(name="shell", args={"cmd": cmd}), state)

    assert decision.allowed is False
    assert "recursive force removal" in decision.reason


def test_local_policy_blocks_patch_path_traversal(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: ../outside.txt",
            "+nope",
            "*** End Patch",
        ]
    )

    decision = LocalPolicy().evaluate(ToolCall(name="apply_patch", args={"patch": patch}), state)

    assert decision.allowed is False
    assert "outside workspace" in decision.reason


def test_local_policy_blocks_patch_symlink_escape(tmp_path) -> None:
    outside = tmp_path / "outside"
    workspace = tmp_path / "workspace"
    outside.mkdir()
    workspace.mkdir()
    try:
        os.symlink(outside, workspace / "escape")
    except (AttributeError, OSError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    state = RunState.create("test", Workspace(workspace), run_id="run_test")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: escape/outside.txt",
            "+nope",
            "*** End Patch",
        ]
    )

    decision = LocalPolicy().evaluate(ToolCall(name="apply_patch", args={"patch": patch}), state)

    assert decision.allowed is False
    assert "outside workspace" in decision.reason


def test_apply_patch_denies_direct_symlink_paths(tmp_path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("original\n")
    try:
        os.symlink(target, tmp_path / "link.txt")
    except (AttributeError, OSError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: link.txt",
            "@@",
            "-original",
            "+changed",
            "*** End Patch",
        ]
    )

    result = ApplyPatchTool().run(ToolCall(name="apply_patch", args={"patch": patch}), state)

    assert result.ok is False
    assert "Cannot patch symlink path: link.txt" in result.output
    assert target.read_text() == "original\n"


def test_local_policy_blocks_explicit_current_run_artifact_search_paths(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    policy = LocalPolicy()

    listed = policy.evaluate(ToolCall(name="list_files", args={"path": ".tinyagent/runs/run_test"}), state)
    searched = policy.evaluate(ToolCall(name="search_repo", args={"path": ".tinyagent/runs/run_test", "query": "secret"}), state)

    assert listed.allowed is False
    assert "current run artifacts" in listed.reason
    assert searched.allowed is False
    assert "current run artifacts" in searched.reason


def test_shell_sanitizes_environment_and_persists_full_output(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("TINYAGENT_MODEL_API_KEY", "tiny-secret")
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    result = ShellTool().run(
        ToolCall(
            name="shell",
            args={
                "cmd": (
                    f"{sys.executable} -c 'import os; "
                    'print(os.environ.get("OPENAI_API_KEY", "missing")); '
                    'print(os.environ.get("TINYAGENT_MODEL_API_KEY", "missing")); '
                    'print(os.environ.get("HOME", "missing"))\''
                )
            },
        ),
        state,
    )

    assert result.ok is True
    assert result.output.splitlines() == ["missing", "missing", str(state.output_dir / "home")]
    assert result.data["cmd"]
    assert result.data["output_chars"] == len(result.output)
    artifact = state.output_dir / result.data["output_artifact"]
    assert artifact.read_text() == result.output


def test_shell_timeout_terminates_process_group_children(tmp_path) -> None:
    child_script = tmp_path / "child.py"
    child_script.write_text(
        "\n".join(
            [
                "import pathlib",
                "import time",
                "pathlib.Path('child.started').write_text('started\\n')",
                "time.sleep(2)",
                "pathlib.Path('child.done').write_text('done\\n')",
            ]
        )
    )
    parent_script = tmp_path / "parent.py"
    parent_script.write_text(
        "\n".join(
            [
                "import pathlib",
                "import subprocess",
                "import sys",
                "import time",
                "subprocess.Popen([sys.executable, 'child.py'])",
                "for _ in range(100):",
                "    if pathlib.Path('child.started').exists():",
                "        break",
                "    time.sleep(0.01)",
                "time.sleep(10)",
            ]
        )
    )
    state = RunState.create("test", Workspace(tmp_path), budgets=RunBudgets(max_shell_timeout_seconds=1), run_id="run_timeout")

    result = ShellTool().run(
        ToolCall(name="shell", args={"cmd": f"{shlex.quote(sys.executable)} parent.py", "timeout_seconds": 1}),
        state,
    )
    time.sleep(2.5)

    assert result.ok is False
    assert result.data["timeout"] is True
    assert (tmp_path / "child.started").exists()
    assert not (tmp_path / "child.done").exists()
    command_finished = next(event for event in state.events if event.type == "CommandFinished")
    assert command_finished.data["timeout"] is True
    assert command_finished.data["output_artifact"] == result.data["output_artifact"]


def test_search_repo_rg_uses_sanitized_environment(tmp_path, monkeypatch) -> None:
    fake_rg = tmp_path / "fake-rg"
    fake_rg.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "import os",
                "print(os.environ.get('OPENAI_API_KEY', 'missing'))",
                "print(os.environ.get('TINYAGENT_MODEL_API_KEY', 'missing'))",
                "print(os.environ.get('HOME', 'missing'))",
            ]
        )
    )
    fake_rg.chmod(0o755)
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("TINYAGENT_MODEL_API_KEY", "tiny-secret")
    monkeypatch.setattr("agentd.tools_repo.shutil.which", lambda _name: str(fake_rg))
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")

    result = SearchRepoTool().run(ToolCall(name="search_repo", args={"query": "needle"}), state)

    assert result.ok is True
    assert result.output.splitlines() == ["missing", "missing", str(state.output_dir / "home")]


def test_search_repo_timeout_terminates_rg_before_output(tmp_path) -> None:
    fake_rg = tmp_path / "slow-rg"
    fake_rg.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import time",
                "time.sleep(5)",
                "print('late match')",
            ]
        )
    )
    fake_rg.chmod(0o755)
    state = RunState.create("test", Workspace(tmp_path), budgets=RunBudgets(max_shell_timeout_seconds=1), run_id="run_test")

    started = time.monotonic()
    lines, truncated, timed_out = _run_rg_limited(state, str(fake_rg), "needle", ".", max_matches=10)

    assert time.monotonic() - started < 3
    assert lines == []
    assert truncated is True
    assert timed_out is True


def test_fallback_search_skips_large_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentd.tools_repo.shutil.which", lambda _name: None)
    (tmp_path / "large.txt").write_text("needle\n" + ("x" * MAX_READ_FILE_BYTES))
    (tmp_path / "small.txt").write_text("needle\n")
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")

    result = SearchRepoTool().run(ToolCall(name="search_repo", args={"query": "needle"}), state)

    assert result.ok is True
    assert "small.txt" in result.output
    assert "large.txt" not in result.output


def test_apply_patch_supports_add_delete_update_move_and_multi_hunk(tmp_path) -> None:
    (tmp_path / "delete.txt").write_text("delete me\n")
    (tmp_path / "edit.txt").write_text("one\ntwo\nthree\nfour\n")
    (tmp_path / "move.txt").write_text("old name\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: added.txt",
            "+added",
            "*** Delete File: delete.txt",
            "*** Update File: edit.txt",
            "@@",
            "-one",
            "+ONE",
            "@@",
            "-three",
            "+THREE",
            "*** Update File: move.txt",
            "*** Move to: moved.txt",
            "@@",
            "-old name",
            "+new name",
            "*** End Patch",
        ]
    )

    output = apply_openai_patch(tmp_path, patch)

    assert "A added.txt" in output
    assert "D delete.txt" in output
    assert "M edit.txt" in output
    assert "R move.txt -> moved.txt" in output
    assert (tmp_path / "added.txt").read_text() == "added\n"
    assert not (tmp_path / "delete.txt").exists()
    assert (tmp_path / "edit.txt").read_text() == "ONE\ntwo\nTHREE\nfour\n"
    assert not (tmp_path / "move.txt").exists()
    assert (tmp_path / "moved.txt").read_text() == "new name\n"


def test_apply_patch_does_not_move_over_existing_file(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    (tmp_path / "source.txt").write_text("source\n")
    (tmp_path / "target.txt").write_text("target\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: source.txt",
            "*** Move to: target.txt",
            "@@",
            "-source",
            "+changed",
            "*** End Patch",
        ]
    )

    result = ApplyPatchTool().run(ToolCall(name="apply_patch", args={"patch": patch}), state)

    assert result.ok is False
    assert "Cannot move over existing file: target.txt" in result.output
    assert (tmp_path / "source.txt").read_text() == "source\n"
    assert (tmp_path / "target.txt").read_text() == "target\n"


def test_apply_patch_failed_hunk_does_not_mutate_file(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    (tmp_path / "edit.txt").write_text("original\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: edit.txt",
            "@@",
            "-missing",
            "+changed",
            "*** End Patch",
        ]
    )

    result = ApplyPatchTool().run(ToolCall(name="apply_patch", args={"patch": patch}), state)

    assert result.ok is False
    assert "Patch hunk did not match" in result.output
    assert (tmp_path / "edit.txt").read_text() == "original\n"


def test_apply_patch_rolls_back_earlier_operation_after_later_failure(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    (tmp_path / "edit.txt").write_text("original\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: created.txt",
            "+created",
            "*** Update File: edit.txt",
            "@@",
            "-original",
            "+changed",
            "*** Update File: missing.txt",
            "@@",
            "-missing",
            "+still missing",
            "*** End Patch",
        ]
    )

    result = ApplyPatchTool().run(ToolCall(name="apply_patch", args={"patch": patch}), state)

    assert result.ok is False
    assert "Cannot update missing file" in result.output
    assert not (tmp_path / "created.txt").exists()
    assert (tmp_path / "edit.txt").read_text() == "original\n"


def test_untracked_file_final_diff_is_valid_unified_diff(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "created.txt").write_text("new file\n")
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")

    capture_final_diff(state)

    assert "diff --git a/created.txt b/created.txt" in state.final_diff
    assert "\n--- /dev/null\n+++ b/created.txt\n" in state.final_diff
    check_root = tmp_path.parent / f"{tmp_path.name}-apply-check"
    check_root.mkdir()
    subprocess.run(["git", "init"], cwd=check_root, check=True, capture_output=True, text=True)
    check = subprocess.run(["git", "apply", "--check"], cwd=check_root, input=state.final_diff, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr


def test_final_diff_includes_staged_changes(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("original\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "tracked.txt").write_text("changed\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")

    capture_final_diff(state)

    assert "-original" in state.final_diff
    assert "+changed" in state.final_diff


def test_apex_profile_caches_system_prompt(tmp_path) -> None:
    prompt_path = tmp_path / "system.md"
    prompt_path.write_text("first")
    profile = ApexCoderProfile(system_prompt_path=prompt_path)

    prompt_path.write_text("second")

    assert profile.system_prompt() == "first"


def test_apex_profile_exposes_only_shell_and_apply_patch_by_default(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    tools = {tool.name: tool for tool in default_tools()}

    visible = ApexCoderProfile().visible_tools(state, tools)

    assert [tool.name for tool in visible] == ["shell", "apply_patch"]


def test_tool_collections_name_builtin_and_repo_groups() -> None:
    assert [tool.name for tool in builtin_tools()] == ["shell", "apply_patch"]
    assert [tool.name for tool in repo_inspect_tools()] == ["read_file", "list_files", "search_repo"]
    assert [tool.name for tool in all_tools()] == ["shell", "apply_patch", "read_file", "list_files", "search_repo"]
    assert [tool.name for tool in default_tools()] == [tool.name for tool in all_tools()]
    assert "finish" not in {tool.name for tool in default_tools()}


def test_apex_profile_visible_tools_are_overridable_for_ablations(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    tools = {tool.name: tool for tool in default_tools()}
    profile = ApexCoderProfile(visible_tool_names=("shell", "apply_patch", "read_file", "search_repo"))

    visible = profile.visible_tools(state, tools)

    assert [tool.name for tool in visible] == ["shell", "apply_patch", "read_file", "search_repo"]


@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("read_file", {"path": "hello.txt"}),
        ("list_files", {}),
        ("search_repo", {"query": "hello"}),
    ],
)
def test_apex_profile_blocks_registered_but_hidden_tools(tmp_path, tool_name, args) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    hidden_call = ToolCall(name=tool_name, args=args)
    model = FakeModelProvider(
        [
            ModelResponse(tool_calls=(hidden_call,)),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    )

    state = kernel.run(f"try hidden {tool_name}", workspace=tmp_path, run_id=f"run_hidden_{tool_name}")

    assert state.failed is False
    assert state.summary == "done"
    assert state.turn_count == 2
    result = state.tool_results[0]
    assert result.tool_name == tool_name
    assert result.ok is False
    assert result.output == f"Tool is not visible for this profile: {tool_name}"
    assert result.data == {"blocked": True, "error_type": "ToolNotVisible", "visible_tools": ["apply_patch", "shell"]}
    hidden_events = [event for event in state.events if event.data.get("tool_call_id") == hidden_call.id]
    assert [event.type for event in hidden_events] == ["ToolCallRequested", "ToolCallFinished"]


def test_shell_preflight_records_expected_interface_in_events_and_metrics(tmp_path) -> None:
    model = FakeModelProvider([ModelResponse(content="done", finish_reason="stop")])
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    )

    state = kernel.run("preflight", workspace=tmp_path, run_id="run_preflight")

    preflight = next(event for event in state.events if event.type == "ShellPreflight")
    assert set(preflight.data["commands"]) == {"rg", "git", "python3", "python", "sed"}
    assert isinstance(preflight.data["python_available"], bool)
    metrics = json.loads((state.output_dir / "metrics.json").read_text())
    assert metrics["shell_preflight"] == state.shell_preflight


def test_golden_trace_calc_pytest_patch_loop_records_required_artifacts(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (tmp_path / "test_calc.py").write_text("from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    subprocess.run(["git", "add", "calc.py", "test_calc.py"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    test_command = f"{shlex.quote(sys.executable)} -m pytest"
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: calc.py",
            "@@",
            "-    return a - b",
            "+    return a + b",
            "*** End Patch",
        ]
    )
    model = FakeModelProvider(
        [
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "sed -n '1,120p' calc.py"}),)),
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": test_command}),)),
            ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": test_command}),)),
            ModelResponse(content="Fixed calc.py and verified tests.", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    )

    state = kernel.run("Fix the bug in calc.py. Run the tests and inspect the final diff.", workspace=tmp_path, run_id="run_calc_golden")

    assert state.failed is False
    assert (tmp_path / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "summary.md").exists()
    assert (state.output_dir / "metrics.json").exists()
    assert (state.output_dir / "final.diff").read_text() == state.final_diff
    assert "-    return a - b" in state.final_diff
    assert "+    return a + b" in state.final_diff

    context_built = next(event for event in state.events if event.type == "ContextBuilt")
    assert isinstance(context_built.data["token_estimate"], int)
    assert context_built.data["token_estimate"] > 0

    model_request = next(event for event in state.events if event.type == "ModelRequest")
    model_response = next(event for event in state.events if event.type == "ModelResponse")
    assert (state.output_dir / model_request.data["context_artifact"]).exists()
    assert (state.output_dir / model_request.data["logical_request_artifact"]).exists()
    assert (state.output_dir / model_response.data["response_artifact"]).exists()

    sed_requested = next(
        event
        for event in state.events
        if event.type == "ToolCallRequested" and event.data["tool"] == "shell" and event.data["args"]["cmd"].startswith("sed ")
    )
    assert sed_requested.data["args_preview"] == sed_requested.data["args"]

    command_finished = [event for event in state.events if event.type == "CommandFinished"]
    assert command_finished
    assert all((state.output_dir / event.data["output_artifact"]).exists() for event in command_finished)
    assert any(event.type == "PatchApplied" and event.data["paths"] == ["calc.py"] for event in state.events)
    assert any(event.type == "DiffSnapshot" and event.data["available"] is True for event in state.events)

    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    replay = replay_run(state.output_dir)

    assert "Tinyagent Replay" in replay
    assert "CommandFinished" in replay
    assert (tmp_path / "calc.py").read_text() == "def add(a, b):\n    return a - b\n"


def test_fake_provider_trace_shells_patches_answers_with_content_and_captures_diff(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "hello.txt").write_text("hello\n")
    subprocess.run(["git", "add", "hello.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)

    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.txt",
            "@@",
            "-hello",
            "+hello tinyagent",
            "*** End Patch",
        ]
    )
    model = FakeModelProvider(
        [
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "sed -n '1,120p' hello.txt"}),)),
            ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "cat hello.txt"}),)),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    )

    state = kernel.run("read, patch, shell, answer", workspace=tmp_path, run_id="run_trace")

    assert state.failed is False
    assert state.summary == "done"
    assert (tmp_path / "hello.txt").read_text() == "hello tinyagent\n"
    assert "-hello" in state.final_diff
    assert "+hello tinyagent" in state.final_diff
    assert (state.output_dir / "final.diff").read_text() == state.final_diff
    event_types = [event.type for event in state.events]
    assert "PatchApplied" in event_types
    assert "CommandStarted" in event_types
    assert "CommandFinished" in event_types
    assert event_types[-1] == "DiffSnapshot"
    patch_result = next(result for result in state.tool_results if result.tool_name == "apply_patch")
    shell_result = [result for result in state.tool_results if result.tool_name == "shell"][-1]
    assert (state.output_dir / patch_result.data["output_artifact"]).exists()
    assert (state.output_dir / shell_result.data["output_artifact"]).read_text() == "hello tinyagent\n"


def test_golden_trace_covers_context_artifacts_tool_args_shell_artifact_and_untracked_diff(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "hello.txt").write_text("hello needle\n")
    subprocess.run(["git", "add", "hello.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)

    shell_call = ToolCall(name="shell", args={"cmd": "printf 'new file\\n' > created.txt && printf 'shell output\\n'"})
    model = FakeModelProvider(
        [
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "sed -n '1,120p' hello.txt"}),)),
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        name="shell",
                        args={
                            "cmd": (
                                "if command -v rg >/dev/null; then rg --glob '!**/.tinyagent/**' needle .; "
                                "else find . -path './.tinyagent' -prune -o -type f -print0 | xargs -0 grep -H needle; fi"
                            )
                        },
                    ),
                )
            ),
            ModelResponse(tool_calls=(shell_call,)),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    )

    state = kernel.run("golden trace", workspace=tmp_path, run_id="run_golden")

    assert state.failed is False
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "final.diff").read_text() == state.final_diff
    assert "created.txt" in state.final_diff
    assert "+new file" in state.final_diff

    model_requests = [event for event in state.events if event.type == "ModelRequest"]
    model_request = model_requests[0]
    model_response = next(event for event in state.events if event.type == "ModelResponse")
    assert (state.output_dir / model_request.data["context_artifact"]).exists()
    assert (state.output_dir / model_request.data["logical_request_artifact"]).exists()
    assert (state.output_dir / model_response.data["response_artifact"]).exists()
    logical_request = json.loads((state.output_dir / model_request.data["logical_request_artifact"]).read_text())
    assert [tool["name"] for tool in logical_request["tools"]] == ["shell", "apply_patch"]
    final_context = (state.output_dir / model_requests[-1].data["context_artifact"]).read_text()
    assert "Tool: shell" in final_context
    assert "created.txt" in final_context
    assert "shell output" in final_context

    shell_requested = [
        event
        for event in state.events
        if event.type == "ToolCallRequested" and event.data["tool"] == "shell" and event.data["tool_call_id"] == shell_call.id
    ][0]
    assert shell_requested.data["args"] == {"cmd": shell_call.args["cmd"]}
    shell_result = next(result for result in state.tool_results if result.tool_name == "shell" and result.call_id == shell_call.id)
    assert (state.output_dir / shell_result.data["output_artifact"]).read_text() == "shell output\n"
    assert shell_result.data["output_chars"] == len("shell output\n")

    replay = replay_run(state.output_dir)
    assert "command-output" in replay
    assert (tmp_path / "created.txt").read_text() == "new file\n"

    metrics = json.loads((state.output_dir / "metrics.json").read_text())
    assert metrics["shell_env"] == "sanitized"
    assert metrics["sandbox_mode"] == "none"
