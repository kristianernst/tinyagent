from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import threading
import time

import pytest

from tinyagent.core.context import estimate_messages_tokens, estimate_tools_tokens
from tinyagent.core.diffs import MAX_UNTRACKED_DIFF_BYTES
from tinyagent.core.index import SearchCodeTool, WorkspaceIndexManager
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import FakeModelProvider, ModelSpec
from tinyagent.core.output import capture_final_diff, write_text_artifact
from tinyagent.core.path_safety import (
    checked_relative_path,
    is_env_file_name,
    looks_like_env_path,
    looks_like_secret_path,
    relative_path_is_within,
    safe_artifact_name,
)
from tinyagent.core.policy import LocalPolicy
from tinyagent.core.profile_catalog import (
    DEFAULT_RUNTIME_CAPABILITIES,
    TINY_PI_RUNTIME_CAPABILITIES,
)
from tinyagent.core.profiles import ApexCoderProfile, TinyPiProfile, profile_for
from tinyagent.core.run_control import CancelToken
from tinyagent.core.state import Message, ModelResponse, PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult, ToolStep, Workspace
from tinyagent.core.tools import (
    ApplyPatchTool,
    ListFilesTool,
    ReadFileTool,
    ShellTool,
    StrReplaceEditTool,
    WriteFileTool,
    all_tools,
    builtin_tools,
    default_tools,
)
from tinyagent.core.tools.builtins.patch import apply_openai_patch
from tinyagent.core.tools.repo import MAX_READ_FILE_BYTES, repo_inspect_tools
from tinyagent.runtime.replay import replay_run


class WorkspaceShellPolicy(LocalPolicy):
    def _evaluate_shell(self, call: ToolCall, state: RunState):
        decision = super()._evaluate_shell(call, state)
        if decision.kind == "needs_approval" and decision.permission == "bash":
            return PolicyDecision.allow("test permits workspace shell", matched_rule="test.bash.allow", permission="bash")
        return decision


def test_path_safety_helpers_cover_artifacts_envs_secrets_and_containment() -> None:
    assert [safe_artifact_name(value) for value in ("call/with spaces:and*chars", "", ".", "..")] == [
        "call_with_spaces_and_chars",
        "call",
        "call",
        "call",
    ]
    assert [is_env_file_name(value) for value in (".env", ".env.local", "config.env")] == [True, True, False]
    assert [looks_like_secret_path(value) for value in (".ssh/config", "package/.npmrc", "src/env.py")] == [True, True, False]
    assert looks_like_env_path("config/.env.local")
    assert checked_relative_path("nested/file.txt").as_posix() == "nested/file.txt"
    for value in ("", "/tmp/file.txt", "../file.txt", "nested/../../file.txt"):
        with pytest.raises(ValueError):
            checked_relative_path(value)
    containment_cases = (("out/file.txt", "out"), ("file.txt", "."), ("output/file.txt", "out"), ("out-file.txt", "out"))
    assert [relative_path_is_within(path, parent) for path, parent in containment_cases] == [True, True, False, False]


def test_write_text_artifact_rejects_names_outside_artifacts(tmp_path) -> None:
    state = RunState.create("artifact boundary", Workspace(tmp_path), run_id="run_artifact_boundary")

    for name in ("../escape.txt", "/tmp/tinyagent-escape.txt", "nested/../../escape.txt", ""):
        with pytest.raises(ValueError):
            write_text_artifact(state, name, "escape\n", kind="test")

    assert not (tmp_path / "escape.txt").exists()
    assert not any(event.type == "artifact.created" for event in state.events)


def test_list_and_code_search_exclude_tinyagent_outputs(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("needle\n")
    trace_dir = tmp_path / ".tinyagent" / "runs" / "run_test"
    trace_dir.mkdir(parents=True)
    (trace_dir / "events.jsonl").write_text("needle\n")
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    state.workspace_index = WorkspaceIndexManager.for_workspace(tmp_path)

    listed = ListFilesTool().run(ToolCall(name="list_files"), state)
    searched = SearchCodeTool().run(ToolCall(name="search_code", args={"query": "needle"}), state)

    assert listed.ok is True
    assert "hello.txt" in listed.output
    assert ".tinyagent" not in listed.output
    assert searched.ok is True
    assert "hello.txt" in searched.output
    assert ".tinyagent" not in searched.output
    assert [event.type for event in state.events] == [
        "files.listed",
        "index.sync.started",
        "index.sync.completed",
        "code.search.completed",
    ]


def test_read_file_emits_artifact_metadata(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("needle\n" * 30)
    state = RunState.create("test", Workspace(tmp_path), run_id="run_structured_inspection")
    state.budgets = RunBudgets(max_command_output_chars_visible=80)

    read = ReadFileTool().run(ToolCall(name="read_file", args={"path": "hello.txt", "max_lines": 30}), state)

    assert read.ok is True
    assert read.artifact_path and read.artifact_path.startswith("context/read_file/")
    assert read.truncated is True
    assert read.read_hints
    assert read.data["path"] == "hello.txt"
    assert read.data["line_count"] == 30


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
    listed_output_dir = ListFilesTool().run(ToolCall(name="list_files", args={"path": "run-output"}), state)
    capture_final_diff(state)

    assert listed.ok is True
    assert listed_output_dir.ok is True
    assert "real.txt" in listed.output
    assert "run-output" not in listed.output
    assert listed_output_dir.output == ""
    assert "real.txt" in state.final_diff
    assert "run-output" not in state.final_diff


def test_final_diff_handles_output_dir_outside_workspace(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    output_dir = tmp_path.parent / "outside-run-output"
    output_dir.mkdir()
    (output_dir / "events.jsonl").write_text("trace\n")
    (tmp_path / "real.txt").write_text("workspace\n")
    state = RunState.create("outside output", Workspace(tmp_path), run_id="run_outside_output", output_dir=output_dir)

    capture_final_diff(state)

    assert "real.txt" in state.final_diff
    assert "outside-run-output" not in state.final_diff


def test_final_diff_skips_untracked_symlink_without_reading_target(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("outside secret\n")
    try:
        os.symlink(outside, tmp_path / "leak")
    except (AttributeError, OSError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    state = RunState.create("test", Workspace(tmp_path), run_id="run_symlink")

    capture_final_diff(state)

    assert "outside secret" not in state.final_diff
    assert "leak" not in state.final_diff


def test_final_diff_caps_large_untracked_file_content(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "large.txt").write_text("secret\n" + ("x" * MAX_UNTRACKED_DIFF_BYTES))
    state = RunState.create("test", Workspace(tmp_path), run_id="run_large")

    capture_final_diff(state)

    assert "secret" not in state.final_diff
    assert "Binary files /dev/null and b/large.txt differ" in state.final_diff


def test_final_diff_excludes_untracked_secret_paths(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / ".env.local").write_text("TOKEN=final-diff-secret\n")
    (tmp_path / ".npmrc").write_text("//registry.example/:_authToken=npm-secret\n")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("Host hidden-ssh-secret\n")
    (tmp_path / "visible.txt").write_text("visible\n")
    state = RunState.create("test", Workspace(tmp_path), run_id="run_secret_final_diff")

    capture_final_diff(state)

    assert "visible.txt" in state.final_diff
    for hidden in ("final-diff-secret", "npm-secret", "hidden-ssh-secret", ".env.local", ".npmrc", ".ssh"):
        assert hidden not in state.final_diff


def test_local_policy_blocks_outside_paths_and_risky_shell(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    policy = LocalPolicy()

    outside = policy.evaluate(ToolCall(name="read_file", args={"path": "../secret.txt"}), state)
    shell = policy.evaluate(ToolCall(name="shell", args={"cmd": "rm -rf build"}), state)
    network = policy.evaluate(ToolCall(name="shell", args={"cmd": "curl https://example.com"}), state)
    redirect = policy.evaluate(ToolCall(name="shell", args={"cmd": "printf x > /tmp/outside.txt"}), state)

    assert outside.allowed is False
    assert "outside workspace" in outside.reason
    assert shell.allowed is False
    assert "denied" in shell.reason
    assert network.kind == "deny"
    assert network.permission == "network"
    assert redirect.kind == "needs_approval"
    assert redirect.approval is not None
    assert redirect.approval.action_kind == "workspace_escape"


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


def test_shell_cancel_kills_command_and_records_cancelled(tmp_path) -> None:
    state = RunState.create("cancel shell", Workspace(tmp_path), run_id="run_cancel_shell")
    call = ToolCall(
        name="shell",
        args={"cmd": f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(20)'", "timeout_seconds": 20},
    )
    result_box: dict[str, object] = {}

    def run_shell() -> None:
        result_box["result"] = ShellTool().run(call, state)

    thread = threading.Thread(target=run_shell)
    thread.start()
    time.sleep(0.2)
    state.request_cancel("test cancellation")
    thread.join(timeout=5)

    assert thread.is_alive() is False
    result = result_box["result"]
    assert isinstance(result, ToolResult)
    assert result.ok is False
    assert result.data["cancelled"] is True
    assert [event.type for event in state.events if event.type in {"run.cancel.requested", "command.cancelled"}] == [
        "run.cancel.requested",
        "command.cancelled",
    ]
    assert not any(
        event.type == "command.completed" and event.data.get("tool_call_id") == call.id for event in state.events
    )
    command = next(event for event in state.events if event.type == "command.cancelled")
    assert command.data["cmd"] == call.args["cmd"]
    assert command.data["output_artifact"].startswith("artifacts/command-output-")


def test_shell_records_execution_envelope_metadata(tmp_path) -> None:
    state = RunState.create("envelope", Workspace(tmp_path), run_id="run_envelope")
    result = ShellTool().run(ToolCall(name="shell", args={"cmd": "printf ok"}), state)

    assert result.ok is True
    envelope = result.metadata["execution_envelope"]
    assert envelope["cwd"] == str(tmp_path)
    assert envelope["env"] == "sanitized"
    assert str(tmp_path) in envelope["writable_roots"]
    assert str(state.output_dir / "home") in envelope["writable_roots"]
    assert envelope["process_group_cancellation"] is True
    command = next(event for event in state.events if event.type == "command.started")
    assert command.data["execution_envelope"] == envelope


def test_kernel_shell_cancel_records_only_cancelled_tool_and_command_events(tmp_path) -> None:
    call = ToolCall(
        name="shell",
        args={"cmd": f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(20)'", "timeout_seconds": 20},
    )
    token = CancelToken()
    kernel = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(call,))]),
        profile=ApexCoderProfile(),
        tools=[ShellTool()],
        policy=WorkspaceShellPolicy(),
    )
    state_box: dict[str, RunState] = {}
    command_started = threading.Event()

    class StartSink:
        def emit(self, event) -> None:
            if event.type == "command.started" and event.data.get("tool_call_id") == call.id:
                command_started.set()

    def run_kernel() -> None:
        state_box["state"] = kernel.run(
            "run a cancellable shell command",
            workspace=tmp_path,
            cancel_token=token,
            event_sink=StartSink(),
        )

    thread = threading.Thread(target=run_kernel)
    thread.start()
    assert command_started.wait(timeout=5) is True
    token.cancel("test cancellation")
    thread.join(timeout=5)

    assert thread.is_alive() is False
    state = state_box["state"]
    assert state.cancelled is True
    command_events = [
        event.type
        for event in state.events
        if event.data.get("tool_call_id") == call.id and event.type.startswith("command.")
    ]
    tool_execution_events = [
        event.type
        for event in state.events
        if event.data.get("tool_call_id") == call.id and event.type.startswith("tool.execution.")
    ]
    assert command_events == ["command.started", "command.cancelled"]
    assert tool_execution_events == ["tool.execution.started", "tool.execution.cancelled"]


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
    searched = policy.evaluate(ToolCall(name="search_code", args={"path": ".tinyagent/runs/run_test", "query": "secret"}), state)

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
                    'print(os.environ.get("HOME", "missing")); '
                    'print(os.environ.get("PYTHONDONTWRITEBYTECODE", "missing"))\''
                )
            },
        ),
        state,
    )

    assert result.ok is True
    assert result.output.splitlines() == ["missing", "missing", str(state.output_dir / "home"), "1"]
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
    command_completed_events = [event for event in state.events if event.type == "command.timeout"]
    assert len(command_completed_events) == 1
    assert "command.cancelled" not in [event.type for event in state.events]
    command_finished = command_completed_events[0]
    assert command_finished.data["timeout"] is True
    assert command_finished.data["capability"] == "process"
    assert command_finished.data["source"] == "tool"
    assert command_finished.data["output_artifact"] == result.data["output_artifact"]
    assert result.data["capability"] == "process"


def test_search_code_python_fallback_skips_large_files(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tinyagent.core.index.rg.shutil.which", lambda _name: None)
    (tmp_path / "large.txt").write_text("needle\n" + ("x" * MAX_READ_FILE_BYTES))
    (tmp_path / "small.txt").write_text("needle\n")
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    state.workspace_index = WorkspaceIndexManager.for_workspace(tmp_path)

    result = SearchCodeTool().run(ToolCall(name="search_code", args={"query": "needle"}), state)

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


def test_str_replace_edit_requires_unique_match_and_updates_file(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    state = RunState.create("edit", Workspace(tmp_path), run_id="run_str_replace")

    result = StrReplaceEditTool().run(
        ToolCall(name="str_replace_edit", args={"path": "hello.txt", "old_str": "hello", "new_str": "hi"}),
        state,
    )

    assert result.ok is True
    assert result.metadata["paths"] == ["hello.txt"]
    assert (tmp_path / "hello.txt").read_text() == "hi\n"


def test_str_replace_edit_rejects_non_unique_match(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("x x\n")
    state = RunState.create("edit", Workspace(tmp_path), run_id="run_str_replace_reject")

    result = StrReplaceEditTool().run(
        ToolCall(name="str_replace_edit", args={"path": "hello.txt", "old_str": "x", "new_str": "y"}),
        state,
    )

    assert result.ok is False
    assert "exactly once" in result.output
    assert (tmp_path / "hello.txt").read_text() == "x x\n"


def test_write_file_overwrites_small_workspace_file(tmp_path) -> None:
    state = RunState.create("edit", Workspace(tmp_path), run_id="run_write_file")

    result = WriteFileTool().run(ToolCall(name="write_file", args={"path": "generated.txt", "content": "hello\n"}), state)

    assert result.ok is True
    assert result.metadata["paths"] == ["generated.txt"]
    assert (tmp_path / "generated.txt").read_text() == "hello\n"


def test_write_file_rolls_back_if_atomic_write_fails(tmp_path, monkeypatch) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("before\n")
    state = RunState.create("edit", Workspace(tmp_path), run_id="run_write_file_rollback")

    def fail_replace(src, dst):
        del src, dst
        raise OSError("replace failed")

    monkeypatch.setattr("tinyagent.core.tools.builtins.edit.os.replace", fail_replace)
    result = WriteFileTool().run(ToolCall(name="write_file", args={"path": "hello.txt", "content": "after\n"}), state)

    assert result.ok is False
    assert "replace failed" in result.output
    assert target.read_text() == "before\n"


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


def _default_kernel_tools() -> dict[str, object]:
    kernel = Kernel(
        model=FakeModelProvider([ModelResponse(content="done")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    )
    return kernel.tools


def test_apex_profile_exposes_structured_inspection_edit_and_shell_by_default(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    tools = _default_kernel_tools()

    visible = ApexCoderProfile().visible_tools(state, tools)

    assert [tool.name for tool in visible] == [
        "read_file",
        "context_search",
        "context_read",
        "search_code",
        "list_skills",
        "load_skill",
        "apply_patch",
        "shell",
    ]


def test_apex_profile_selects_claude_like_edit_tool_from_model_spec(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    state.model_spec = ModelSpec(provider="anthropic", model="claude", protocol="anthropic", edit_style="str_replace").to_json_dict()
    tools = _default_kernel_tools()

    visible = ApexCoderProfile().visible_tools(state, tools)

    assert [tool.name for tool in visible] == [
        "read_file",
        "context_search",
        "context_read",
        "search_code",
        "list_skills",
        "load_skill",
        "str_replace_edit",
        "shell",
    ]


def test_apex_profile_selects_generic_write_file_tool_from_model_spec(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    state.model_spec = ModelSpec(provider="generic", model="text", edit_style="whole_file").to_json_dict()
    tools = _default_kernel_tools()

    visible = ApexCoderProfile().visible_tools(state, tools)

    assert [tool.name for tool in visible] == [
        "read_file",
        "context_search",
        "context_read",
        "search_code",
        "list_skills",
        "load_skill",
        "write_file",
        "shell",
    ]


def test_tool_collections_name_builtin_and_repo_groups() -> None:
    assert [tool.name for tool in builtin_tools()] == ["shell", "apply_patch", "str_replace_edit", "write_file"]
    assert [tool.name for tool in repo_inspect_tools()] == ["read_file", "list_files"]
    assert [tool.name for tool in all_tools()] == [
        "shell",
        "apply_patch",
        "str_replace_edit",
        "write_file",
        "read_file",
        "list_files",
    ]
    assert [tool.name for tool in default_tools()] == [tool.name for tool in all_tools()]
    assert "finish" not in {tool.name for tool in default_tools()}


def test_tools_public_export_surface_stays_small() -> None:
    import tinyagent.core.tools as tools

    assert sorted(tools.__all__) == [
        "ApplyPatchTool",
        "ListFilesTool",
        "ReadFileTool",
        "ShellTool",
        "StrReplaceEditTool",
        "WriteFileTool",
        "all_tools",
        "builtin_tools",
        "default_tools",
        "patch_paths",
        "resolve_workspace_path",
    ]


def test_apex_profile_visible_tools_are_overridable_for_ablations(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_test")
    tools = _default_kernel_tools()
    profile = ApexCoderProfile(visible_tool_names=("shell", "apply_patch", "read_file", "search_code"))

    visible = profile.visible_tools(state, tools)

    assert [tool.name for tool in visible] == ["shell", "apply_patch", "read_file", "search_code"]


def test_tiny_pi_profile_has_minimal_tool_surface_and_context(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_tiny_pi")
    tools = _default_kernel_tools()

    profile = TinyPiProfile()
    visible = profile.visible_tools(state, tools)
    context = profile.build_context(state)
    combined = "\n".join(str(message.content) for message in context.messages)

    assert [tool.name for tool in visible] == ["read_file", "apply_patch", "shell"]
    assert estimate_tools_tokens(visible) < estimate_tools_tokens(ApexCoderProfile().visible_tools(state, tools))
    assert estimate_messages_tokens(context.messages) < estimate_messages_tokens(ApexCoderProfile().build_messages(state))
    assert "Dynamic context sources:" not in combined
    assert "ContextFS index" not in combined


def test_tiny_pi_profile_renders_finish_gate_and_prior_conversation(tmp_path) -> None:
    state = RunState.create(
        "follow up",
        Workspace(tmp_path),
        run_id="run_tiny_pi_conversation",
        prior_messages=(Message(role="user", content="previous turn"),),
    )
    state.finish_gate_messages.append("Do not claim tests passed.")

    combined = "\n".join(str(message.content) for message in TinyPiProfile().build_context(state).messages)

    assert "previous turn" in combined
    assert "Do not claim tests passed." in combined
    assert "Dynamic context sources:" not in combined


def test_tiny_pi_profile_selects_model_specific_edit_tool(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_tiny_pi_edit_style")
    state.model_spec = ModelSpec(provider="anthropic", model="claude", protocol="anthropic", edit_style="str_replace").to_json_dict()
    tools = _default_kernel_tools()

    visible = TinyPiProfile().visible_tools(state, tools)

    assert [tool.name for tool in visible] == ["read_file", "str_replace_edit", "shell"]


@pytest.mark.parametrize(
    ("edit_style", "edit_tool"),
    [("str_replace", "str_replace_edit"), ("whole_file", "write_file")],
)
def test_tiny_pi_kernel_keeps_model_specific_edit_tool(tmp_path, edit_style, edit_tool) -> None:
    class CapturingModel:
        name = "capturing"
        model_spec = ModelSpec(provider="capturing", model="capturing", edit_style=edit_style)

        def __init__(self) -> None:
            self.tools: list[str] = []

        def complete(self, messages, tools, state):
            del messages, state
            self.tools = [tool.name for tool in tools]
            return ModelResponse(content="done", finish_reason="stop")

    model = CapturingModel()
    state = Kernel(
        model=model,
        profile=TinyPiProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    ).run("done", workspace=tmp_path, output_dir=tmp_path / "run")

    assert model.tools == ["read_file", edit_tool, "shell"]
    started = next(event for event in state.events if event.type == "run.started")
    context = next(event for event in state.events if event.type == "context.built")
    assert started.data["profile_visible_tools"] == ["read_file", edit_tool, "shell"]
    assert context.data["visible_tools"] == ["read_file", edit_tool, "shell"]


def test_profile_for_aliases_and_errors() -> None:
    assert isinstance(profile_for("tiny-coder"), ApexCoderProfile)
    assert isinstance(profile_for("pi"), TinyPiProfile)
    with pytest.raises(ValueError, match="Unknown profile"):
        profile_for("unknown")


def test_profile_runtime_capabilities_match_profile_catalog() -> None:
    assert ApexCoderProfile.runtime_capabilities is DEFAULT_RUNTIME_CAPABILITIES
    assert TinyPiProfile.runtime_capabilities is TINY_PI_RUNTIME_CAPABILITIES
    assert profile_for("tiny-coder").runtime_capabilities is DEFAULT_RUNTIME_CAPABILITIES
    assert profile_for("pi").runtime_capabilities is TINY_PI_RUNTIME_CAPABILITIES
    assert profile_for("minimal").runtime_capabilities is TINY_PI_RUNTIME_CAPABILITIES


def test_tiny_pi_truthfulness_gate_without_strict_apex_finish_gate(tmp_path) -> None:
    state = RunState.create("test", Workspace(tmp_path), run_id="run_tiny_pi_finish")
    state.tool_steps.append(
        ToolStep(
            ToolCall(name="apply_patch"),
            ToolResult(tool_name="apply_patch", output="patched", ok=True, metadata={"paths": ["hello.txt"]}),
        )
    )
    profile = TinyPiProfile()

    allowed = profile.before_finish(state, ModelResponse(content="Changed hello.txt.", finish_reason="stop"))
    blocked = profile.before_finish(state, ModelResponse(content="Changed hello.txt. Tests passed.", finish_reason="stop"))
    blocked_suite = profile.before_finish(
        state,
        ModelResponse(content="Changed hello.txt. The test suite passes.", finish_reason="stop"),
    )
    blocked_checks = profile.before_finish(
        state,
        ModelResponse(content="Changed hello.txt. Checks are green.", finish_reason="stop"),
    )

    assert allowed.allow is True
    assert blocked.allow is False
    assert blocked_suite.allow is False
    assert blocked_checks.allow is False
    assert "tests passed" in blocked.reason


@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("list_files", {}),
        ("str_replace_edit", {"path": "hello.txt", "old_str": "hello", "new_str": "hi"}),
    ],
)
def test_apex_profile_blocks_registered_but_hidden_tools(tmp_path, tool_name, args) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    hidden_call = ToolCall(name=tool_name, args=args)
    model = FakeModelProvider(
        [
            ModelResponse(tool_calls=(hidden_call,)),
            ModelResponse(content=f"Blocked hidden tool {tool_name}; no changes made.", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=WorkspaceShellPolicy(),
    )

    state = kernel.run(f"try hidden {tool_name}", workspace=tmp_path, run_id=f"run_hidden_{tool_name}")

    assert state.failed is False
    assert state.final_output == f"Blocked hidden tool {tool_name}; no changes made."
    assert state.turn_count == 1
    assert state.model_call_count == 2
    result = state.tool_results[0]
    assert result.tool_name == tool_name
    assert result.ok is False
    assert result.output == f"Tool is not visible for this profile: {tool_name}"
    assert result.data == {
        "blocked": True,
        "error_type": "ToolNotVisible",
        "visible_tools": [
            "apply_patch",
            "context_read",
            "context_search",
            "list_skills",
            "load_skill",
            "read_file",
            "search_code",
            "shell",
        ],
    }
    hidden_events = [event for event in state.events if event.data.get("tool_call_id") == hidden_call.id]
    assert [event.type for event in hidden_events] == [
        "model.tool_call.assembly.started",
        "model.tool_call.assembly.completed",
        "tool.execution.failed",
        "tool.execution.blocked",
        "contextfs.index.updated",
    ]


def test_shell_preflight_records_expected_interface_in_events_and_metrics(tmp_path) -> None:
    model = FakeModelProvider([ModelResponse(content="done", finish_reason="stop")])
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=WorkspaceShellPolicy(),
    )

    state = kernel.run("preflight", workspace=tmp_path, run_id="run_preflight")

    preflight = next(event for event in state.events if event.type == "shell.preflight.completed")
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
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff -- calc.py"}),)),
            ModelResponse(content="Fixed calc.py and verified tests.", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=WorkspaceShellPolicy(),
    )

    state = kernel.run(
        "Fix the bug in calc.py. Run the tests and inspect the final diff.",
        workspace=tmp_path,
        run_id="run_calc_golden",
        workspace_mode="current",
    )

    assert state.failed is False
    assert (tmp_path / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "final.md").exists()
    assert (state.output_dir / "metrics.json").exists()
    assert (state.output_dir / "final.diff").read_text() == state.final_diff
    assert "-    return a - b" in state.final_diff
    assert "+    return a + b" in state.final_diff

    context_built = next(event for event in state.events if event.type == "context.built")
    assert isinstance(context_built.data["token_estimate"], int)
    assert context_built.data["token_estimate"] > 0

    model_request = next(event for event in state.events if event.type == "model.call.started")
    model_response = next(event for event in state.events if event.type == "model.call.completed")
    assert (state.output_dir / model_request.data["context_artifact"]).exists()
    assert (state.output_dir / model_request.data["logical_request_artifact"]).exists()
    assert (state.output_dir / model_response.data["response_artifact"]).exists()

    sed_requested = next(
        event
        for event in state.events
        if (
            event.type == "model.tool_call.assembly.completed"
            and event.data["tool"] == "shell"
            and event.data["args"]["cmd"].startswith("sed ")
        )
    )
    assert sed_requested.data["args"]["cmd"].startswith("sed ")

    command_finished = [event for event in state.events if event.type == "command.completed"]
    assert command_finished
    assert all((state.output_dir / event.data["output_artifact"]).exists() for event in command_finished)
    assert any(event.type == "patch.applied" and event.data["paths"] == ["calc.py"] for event in state.events)
    assert any(event.type == "diff.finalized" and event.data["available"] is True for event in state.events)

    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    replay = replay_run(state.output_dir)

    assert "Tinyagent Replay" in replay
    assert "command.completed" in replay
    assert (tmp_path / "calc.py").read_text() == "def add(a, b):\n    return a - b\n"


def test_workspace_auto_uses_worktree_for_clean_git_repo(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "hello.txt").write_text("hello\n")
    subprocess.run(["git", "add", "hello.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.txt",
            "@@",
            "-hello",
            "+hello from worktree",
            "*** End Patch",
        ]
    )
    model = FakeModelProvider(
        [
            ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff -- hello.txt"}),)),
            ModelResponse(content="done; verification not run for this worktree smoke test.", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    )

    state = kernel.run("patch safely", workspace=tmp_path, run_id="run_worktree_auto")

    assert state.failed is False
    assert state.workspace.root != tmp_path.resolve()
    assert (tmp_path / "hello.txt").read_text() == "hello\n"
    assert (state.workspace.root / "hello.txt").read_text() == "hello from worktree\n"
    assert any(event.type == "worktree.created" for event in state.events)
    boundary = next(event for event in state.events if event.type == "workspace.boundary")
    assert boundary.data["mode"] == "auto"
    assert boundary.data["effective_mode"] == "worktree"
    metrics = json.loads((state.output_dir / "metrics.json").read_text())
    assert metrics["workspace_mode"] == "auto"
    assert metrics["workspace_effective_mode"] == "worktree"


def test_yolo_approval_mode_does_not_allow_network_shell(tmp_path) -> None:
    shell_call = ToolCall(name="shell", args={"cmd": "curl https://example.com"})
    model = FakeModelProvider(
        [
            ModelResponse(tool_calls=(shell_call,)),
            ModelResponse(content="Network command was denied by policy; no command ran.", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        approval_mode="yolo",
    )

    state = kernel.run("try network", workspace=tmp_path, run_id="run_network_block")

    assert state.failed is False
    assert "command.started" not in [event.type for event in state.events]
    assert not any(event.type == "approval.requested" for event in state.events)
    denial = next(event for event in state.events if event.type == "policy.evaluated" and event.data["tool_call_id"] == shell_call.id)
    assert denial.data["kind"] == "deny"
    assert denial.data["permission"] == "network"
    blocked = next(event for event in state.events if event.type == "tool.execution.blocked")
    assert blocked.data["tool_call_id"] == shell_call.id


def test_default_yolo_approval_mode_does_not_execute_unknown_shell(tmp_path) -> None:
    script = "from pathlib import Path; Path('created.txt').write_text('created')"
    shell_call = ToolCall(name="shell", args={"cmd": f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}"})
    model = FakeModelProvider(
        [
            ModelResponse(tool_calls=(shell_call,)),
            ModelResponse(content="Unknown shell command was denied.", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    )

    state = kernel.run("try unknown shell write", workspace=tmp_path, run_id="run_unknown_shell_block")

    assert state.failed is False
    assert not (tmp_path / "created.txt").exists()
    assert "command.started" not in [event.type for event in state.events]
    resolution = next(event for event in state.events if event.type == "approval.resolved")
    assert resolution.data["decision"] == "denied"
    assert resolution.data["reason"] == "approval-mode=yolo does not allow shell"
    blocked = next(event for event in state.events if event.type == "tool.execution.blocked")
    assert blocked.data["tool_call_id"] == shell_call.id


def test_read_only_shell_allowlist_rejects_workspace_writes(tmp_path) -> None:
    (tmp_path / "source.txt").write_text("secret\n")
    state = RunState.create("policy", Workspace(tmp_path), run_id="run_readonly_shell_policy")
    policy = LocalPolicy()

    redirected_cat = policy.evaluate(ToolCall(name="shell", args={"cmd": "cat source.txt > copy.txt"}), state)
    sed_in_place = policy.evaluate(ToolCall(name="shell", args={"cmd": "sed -i s/secret/public/ source.txt"}), state)
    git_diff_output = policy.evaluate(ToolCall(name="shell", args={"cmd": "git diff --output=audit.diff"}), state)

    assert redirected_cat.kind == "needs_approval"
    assert redirected_cat.matched_rule == "bash.workspace_write"
    assert redirected_cat.permission == "bash"
    assert sed_in_place.kind == "needs_approval"
    assert sed_in_place.matched_rule == "bash.read_only_mutation"
    assert git_diff_output.kind == "needs_approval"
    assert git_diff_output.matched_rule == "bash.read_only_mutation"


@pytest.mark.parametrize(
    "cmd",
    [
        "cat ../outside-secret.txt",
        "head ../outside-secret.txt",
        "tail ../outside-secret.txt",
        "sed -n '1,2p' ../outside-secret.txt",
        "rg secret ..",
        "git diff --no-index ../outside-secret.txt inside.txt",
    ],
)
def test_read_only_shell_allowlist_rejects_outside_reads(tmp_path, cmd: str) -> None:
    (tmp_path / "inside.txt").write_text("inside\n")
    (tmp_path.parent / "outside-secret.txt").write_text("outside\n")
    state = RunState.create("policy", Workspace(tmp_path), run_id="run_readonly_shell_read_policy")
    policy = LocalPolicy()

    decision = policy.evaluate(ToolCall(name="shell", args={"cmd": cmd}), state)

    assert decision.kind == "needs_approval"
    assert decision.matched_rule == "external_directory:*:ask"
    assert decision.permission == "external_directory"
    assert decision.approval is not None
    assert decision.approval.action_kind == "workspace_escape"


@pytest.mark.parametrize(
    "cmd",
    [
        "cat inside.txt",
        "sed -n '1,2p' inside.txt",
        "rg inside .",
        "git diff -- inside.txt",
    ],
)
def test_read_only_shell_allowlist_keeps_workspace_reads_allowed(tmp_path, cmd: str) -> None:
    (tmp_path / "inside.txt").write_text("inside\n")
    state = RunState.create("policy", Workspace(tmp_path), run_id="run_readonly_shell_workspace_read_policy")
    policy = LocalPolicy()

    decision = policy.evaluate(ToolCall(name="shell", args={"cmd": cmd}), state)

    assert decision.allowed is True


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
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff -- hello.txt"}),)),
            ModelResponse(content="done; verification not run for this trace smoke test.", finish_reason="stop"),
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
    assert state.final_output == "done; verification not run for this trace smoke test."
    assert (tmp_path / "hello.txt").read_text() == "hello tinyagent\n"
    assert "-hello" in state.final_diff
    assert "+hello tinyagent" in state.final_diff
    assert (state.output_dir / "final.diff").read_text() == state.final_diff
    event_types = [event.type for event in state.events]
    assert "patch.applied" in event_types
    assert "command.started" in event_types
    assert "command.completed" in event_types
    assert event_types[-1] == "run.completed"
    assert "turn.completed" in event_types
    patch_result = next(result for result in state.tool_results if result.tool_name == "apply_patch")
    shell_result = next(
        result
        for step, result in [(step, step.result) for step in state.tool_steps]
        if step.call.args.get("cmd") == "cat hello.txt"
    )
    assert (state.output_dir / patch_result.data["output_artifact"]).exists()
    assert (state.output_dir / shell_result.data["output_artifact"]).read_text() == "hello tinyagent\n"


def test_golden_streaming_trace_runs_shell_then_finalizes(tmp_path) -> None:
    shell_call = ToolCall(name="shell", args={"cmd": "printf 'shell output\\n'"})
    model = FakeModelProvider(
        [
            ModelResponse(tool_calls=(shell_call,), finish_reason="tool_calls"),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=WorkspaceShellPolicy(),
        stream=True,
    )

    state = kernel.run("stream shell then answer", workspace=tmp_path, run_id="run_stream_golden")

    assert state.failed is False
    assert state.final_output == "done"
    filtered = [event.type for event in state.events if event.type != "artifact.created"]
    assert "workspace.boundary" in filtered
    assert "turn.started" in filtered
    assert "model.call.started" in filtered
    assert "model.tool_call.assembly.completed" in filtered
    assert "policy.evaluated" in filtered
    assert "tool.execution.started" in filtered
    assert "command.started" in filtered
    assert "command.completed" in filtered
    assert "tool.execution.completed" in filtered
    assert "model.message.completed" in filtered
    assert filtered[-1] == "run.completed"
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "final.md").read_text() == "# Final output\n\ndone\n"
    assert (state.output_dir / "metrics.json").exists()
    shell_result = next(result for result in state.tool_results if result.tool_name == "shell")
    assert (state.output_dir / shell_result.data["output_artifact"]).read_text() == "shell output\n"


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
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff -- created.txt"}),)),
            ModelResponse(content="done. Could not run verification in this environment.", finish_reason="stop"),
        ]
    )
    kernel = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=WorkspaceShellPolicy(),
    )

    state = kernel.run("golden trace", workspace=tmp_path, run_id="run_golden")

    assert state.failed is False
    assert (state.output_dir / "events.jsonl").exists()
    assert (state.output_dir / "final.diff").read_text() == state.final_diff
    assert "created.txt" in state.final_diff
    assert "+new file" in state.final_diff

    model_requests = [event for event in state.events if event.type == "model.call.started"]
    model_request = model_requests[0]
    model_response = next(event for event in state.events if event.type == "model.call.completed")
    assert (state.output_dir / model_request.data["context_artifact"]).exists()
    assert (state.output_dir / model_request.data["logical_request_artifact"]).exists()
    assert (state.output_dir / model_response.data["response_artifact"]).exists()
    logical_request = json.loads((state.output_dir / model_request.data["logical_request_artifact"]).read_text())
    assert [tool["name"] for tool in logical_request["tools"]] == [
        "read_file",
        "context_search",
        "context_read",
        "search_code",
        "list_skills",
        "load_skill",
        "apply_patch",
        "shell",
    ]
    final_context = (state.output_dir / model_requests[-1].data["context_artifact"]).read_text()
    assert "Tool: shell" in final_context
    assert "created.txt" in final_context
    assert "shell output" in final_context

    shell_requested = [
        event
        for event in state.events
        if (
            event.type == "model.tool_call.assembly.completed"
            and event.data["tool"] == "shell"
            and event.data["tool_call_id"] == shell_call.id
        )
    ][0]
    assert shell_requested.data["args"] == {"cmd": shell_call.args["cmd"]}
    shell_result = next(result for result in state.tool_results if result.tool_name == "shell" and result.call_id == shell_call.id)
    assert (state.output_dir / shell_result.data["output_artifact"]).read_text() == "shell output\n"
    assert shell_result.data["output_chars"] == len("shell output\n")

    replay = replay_run(state.output_dir)
    assert "context/shell" in replay
    assert (tmp_path / "created.txt").read_text() == "new file\n"

    metrics = json.loads((state.output_dir / "metrics.json").read_text())
    assert metrics["shell_env"] == "sanitized"
    assert metrics["shell_process_group"] == "posix"
    assert metrics["sandbox_mode"] == "none"
