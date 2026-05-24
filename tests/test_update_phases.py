from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tinyagent.core.context import BuiltContext, ContextConfig, estimate_messages_tokens, estimate_tools_tokens
from tinyagent.core.context_sources import ContextReadTool
from tinyagent.core.contextfs import read_hints, refresh_contextfs
from tinyagent.core.execution import build_execution_envelope
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.observations import Observation
from tinyagent.core.output import write_text_artifact
from tinyagent.core.policy import LocalPolicy, PolicyConfig, PolicyRule
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.progress import ProgressGuard
from tinyagent.core.sdk import Agent
from tinyagent.core.state import Message, ModelResponse, PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult, ToolStep, Workspace
from tinyagent.core.token_utils import estimate_tokens
from tinyagent.core.tools import ShellTool, default_tools
from tinyagent.core.workspace import WorkspaceEnvelope
from tinyagent.core.workspace_delta import WorkspaceDeltaObserver
from tinyagent.evals.metrics import evaluate_thresholds, extract_run_metrics
from tinyagent.runtime.run_graph import fork_run


class RecordingModel:
    name = "recording"

    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def complete(self, messages, tools, request):
        del tools, request
        self.messages.append(list(messages))
        return self.responses.pop(0)


class AllowAllPolicy:
    def evaluate(self, call, state):
        del call, state
        return PolicyDecision.allow()


class WorkspaceShellPolicy(LocalPolicy):
    def _evaluate_shell(self, call: ToolCall, state: RunState) -> PolicyDecision:
        decision = super()._evaluate_shell(call, state)
        if decision.kind == "needs_approval" and decision.permission == "bash":
            return PolicyDecision.allow("test permits workspace shell", matched_rule="test.bash.allow", permission="bash")
        return decision


def workspace_shell_policy() -> LocalPolicy:
    return WorkspaceShellPolicy()


def test_toolresult_contextfs_and_context_report_contracts(tmp_path) -> None:
    call = ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"print('x' * 80)\""})
    kernel = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(call,)), ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        budgets=RunBudgets(max_tool_output_tokens_visible=4),
        workspace_mode="current",
    )

    state = kernel.run("produce long output", workspace=tmp_path, run_id="run_contextfs_contract")

    assert state.failed is False
    result = state.tool_results[0]
    assert result.truncated is True
    assert result.artifact_path and result.artifact_path.startswith("context/shell/")
    assert result.read_hints and result.read_hints[0].startswith("tail -120 .tinyagent/runs/run_contextfs_contract/context/shell/")
    assert (state.output_dir / result.artifact_path).read_text() == ("x" * 80) + "\n"
    reread = ShellTool().run(ToolCall(name="shell", args={"cmd": result.read_hints[0]}), state)
    assert reread.ok is True
    assert reread.data["output_tokens"] >= estimate_tokens("x" * 80)
    index = (state.output_dir / "context" / "INDEX.md").read_text()
    assert result.artifact_path in index
    report_event = next(event for event in state.events if event.type == "context.report.written")
    report = json.loads((state.output_dir / report_event.data["context_report_artifact"]).read_text())
    assert any(item["id"] == "contextfs:index" for item in report["included"])
    assert report["context_plan"]["mode"] in {"explore", "finish"}
    assert report["model_capabilities"]["supports_tools"] is True


def test_transcript_records_model_tool_result_and_finish_gate(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.txt",
            "@@",
            "-hello",
            "+hello updated",
            "*** End Patch",
        ]
    )
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(id="call_patch", name="apply_patch", args={"patch": patch}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("edit then finish too early", workspace=tmp_path, run_id="run_transcript_contract")

    assert state.failed is True
    state.transcript.validate_complete()
    items = state.transcript.items
    assert [item.kind for item in items].count("model_response") == 2
    tool_call = next(item for item in items if item.kind == "tool_call")
    tool_result = next(item for item in items if item.kind == "tool_result")
    finish_gate = next(item for item in items if item.kind == "finish_gate")
    assert tool_call.tool_call_id == "call_patch"
    assert tool_result.tool_call_id == "call_patch"
    assert tool_result.artifact_refs
    assert "inspect changed files" in finish_gate.summary
    assert state.transcript.to_json_dict()["pending_tool_call_ids"] == []


def test_finish_gate_accepts_successful_inline_python_assertion_after_edit(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "hello.py").write_text("VALUE = 1\n")
    subprocess.run(["git", "add", "hello.py"], cwd=tmp_path, check=True, capture_output=True, text=True)
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
            "*** Update File: hello.py",
            "@@",
            "-VALUE = 1",
            "+VALUE = 2",
            "*** End Patch",
        ]
    )
    verify_cmd = (
        f'{sys.executable} -c "from pathlib import Path; '
        "assert Path('hello.py').read_text() == 'VALUE = 2\\\\n'; "
        "print('inline verification passed')\""
    )
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "hello.py"}),)),
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff -- hello.py"}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": verify_cmd}),)),
                ModelResponse(content="Changed hello.py and verified with an inline assertion.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("edit and verify with a focused inline assertion", workspace=tmp_path, run_id="run_inline_assert_verify")

    assert state.failed is False
    assert (tmp_path / "hello.py").read_text() == "VALUE = 2\n"
    assert not any(event.type == "finish.blocked" for event in state.events)


def test_observations_classify_patch_diff_verification_and_policy(tmp_path) -> None:
    (tmp_path / "hello.py").write_text("def test_ok():\n    assert True\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.py",
            "@@",
            "-def test_ok():",
            "+def test_ok():",
            "     assert True",
            "*** End Patch",
        ]
    )
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "hello.py"}),)),
                ModelResponse(tool_calls=(ToolCall(name="search_code", args={"query": "test_ok"}),)),
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff --no-index hello.py hello.py"}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -m pytest hello.py"}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "curl https://example.com"}),)),
                ModelResponse(content="Done. Network command was blocked by policy. Verification passed.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
        approval_mode="never",
    ).run("record observations", workspace=tmp_path, run_id="run_observations_contract")

    kinds = [observation.kind for observation in state.observations]
    assert "file_read" in kinds
    assert "search_result" in kinds
    assert "patch_applied" in kinds
    assert "file_changed" in kinds
    assert "diff_seen" in kinds
    assert "verification" in kinds
    assert "policy_block" in kinds
    assert any(event.type == "observation.recorded" for event in state.events)


def test_contextfs_recovery_files_expose_task_diff_observations_transcript_and_tools(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "generated.txt").write_text("hello contextfs\n")
    (tmp_path / ".env").write_text("TOKEN=secret-contextfs\n")
    state = RunState.create("recover contextfs state", Workspace(tmp_path), run_id="run_contextfs_recovery")
    state.output_dir.mkdir(parents=True, exist_ok=True)
    delta = write_text_artifact(state, "workspace-delta-0001.patch", "diff --git a/generated.txt b/generated.txt\n", kind="workspace_delta")
    state.emit("diff.snapshot", {"tool_call_id": "call_shell", "path": delta, "paths": ["generated.txt"]})
    state.emit("command.completed", {"cmd": f"{sys.executable} -m unittest discover -s .", "ok": True, "returncode": 0})
    state.observations.extend(
        [
            Observation(
                kind="file_changed",
                subject="generated.txt",
                summary="generated.txt changed by shell.",
                refs=(delta,),
                data={"source": "workspace_delta"},
            ),
            Observation(
                kind="verification",
                subject="unittest",
                summary="Verification command passed.",
                data={"cmd": f"{sys.executable} -m unittest discover -s ."},
            ),
            Observation(
                kind="policy_block",
                subject="network",
                summary="Network command was blocked by policy.",
                data={"capability": "network", "source": "policy"},
            ),
            Observation(
                kind="sandbox_block",
                subject="filesystem",
                summary="Filesystem write was blocked by sandbox.",
                data={"capability": "filesystem", "source": "sandbox"},
            ),
        ]
    )
    search_call = ToolCall(id="call_search", name="search_code", args={"query": "hello contextfs"})
    search_result = ToolResult(
        tool_name="search_code",
        call_id="call_search",
        output="generated.txt:1:hello contextfs",
        data={"query": "hello contextfs", "result_count": 1},
    )
    state.tool_steps.append(ToolStep(call=search_call, result=search_result))
    state.transcript.record_tool_call(
        item_id="transcript-tool-call-0001",
        turn_id="turn-0001",
        model_call_id="model-call-0001",
        tool_call_id="call_search",
        tool_name="search_code",
        args={"query": "hello contextfs"},
    )
    state.transcript.record_tool_result(
        item_id="transcript-tool-result-0002",
        turn_id="turn-0001",
        tool_call_id="call_search",
        tool_name="search_code",
        ok=True,
        summary="generated.txt:1:hello contextfs",
        failure_kind=None,
    )
    (state.output_dir / "events.jsonl").write_text(
        json.dumps(
            {
                "seq": 1,
                "type": "command.completed",
                "time": "2026-05-03T00:00:00Z",
                "visibility": "debug",
                "data": {"cmd": "curl https://example.com?token=raw-history-secret", "output_preview": "raw-history-secret"},
                "artifact_refs": ["artifacts/model-response-0001.json"],
            }
        )
        + "\n"
    )
    refresh_contextfs(state)

    for relative in [
        "context/INDEX.md",
        "context/task.md",
        "context/current_status.md",
        "context/current_diff.patch",
        "context/last_failure.md",
        "context/observations.md",
        "context/transcript.md",
        "context/history/raw.jsonl",
        "context/history/summary.md",
        "context/tools/INDEX.md",
        "context/tools/read_file.md",
        "context/tools/context_search.md",
        "context/tools/context_read.md",
        "context/tools/search_code.md",
        "context/tools/shell.md",
        "context/diffs/INDEX.md",
    ]:
        assert (state.output_dir / relative).exists(), relative

    diff = (state.output_dir / "context" / "current_diff.patch").read_text()
    assert "generated.txt" in diff
    assert ".tinyagent" not in diff
    assert "secret-contextfs" not in diff
    assert "secret-contextfs" not in (state.output_dir / "context" / "current_status.md").read_text()
    raw_history = (state.output_dir / "context" / "history" / "raw.jsonl").read_text()
    assert "raw-history-secret" not in raw_history
    assert "model-response-0001" not in raw_history
    observations = (state.output_dir / "context" / "observations.md").read_text()
    assert "file_changed" in observations
    assert "verification" in observations
    transcript = (state.output_dir / "context" / "transcript.md").read_text()
    assert "tool_call_id:" in transcript
    assert "tool_result" in transcript
    assert "Workspace code and docs search results" in (state.output_dir / "context" / "tools" / "search_code.md").read_text()

    reader = ContextReadTool()
    for relative in [
        "context/INDEX.md",
        "context/current_diff.patch",
        "context/observations.md",
        "context/transcript.md",
        "context/tools/search_code.md",
    ]:
        result = reader.run(ToolCall(name="context_read", args={"ref": f"contextfs:{relative}"}), state)
        assert result.ok is True, result.output


def test_context_read_safely_allows_recovery_artifacts_but_not_raw_model_artifacts(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="search_code", args={"query": "needle"}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("context reader safety", workspace=tmp_path, run_id="run_context_reader_safety")

    state.output_dir.mkdir(parents=True, exist_ok=True)
    context_report = next(
        event.data["path"] for event in state.events if event.type == "artifact.created" and event.data["kind"] == "context_report"
    )
    reader = ContextReadTool()

    assert reader.run(ToolCall(name="context_read", args={"ref": "contextfs:context/INDEX.md"}), state).ok is True
    assert reader.run(ToolCall(name="context_read", args={"ref": f"contextfs:{context_report}"}), state).ok is False
    assert reader.run(ToolCall(name="context_read", args={"ref": "contextfs:events.jsonl"}), state).ok is False
    assert reader.run(ToolCall(name="context_read", args={"ref": "contextfs:artifacts/model-response-0001.json"}), state).ok is False
    forged_checkpoint = state.output_dir / "artifacts" / "context-checkpoint-9999.md"
    forged_checkpoint.write_text("forged checkpoint\n")
    assert reader.run(ToolCall(name="context_read", args={"ref": "contextfs:artifacts/context-checkpoint-9999.md"}), state).ok is False


def test_contextfs_diff_excludes_custom_output_dir_symlinks_and_large_files(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("outside-secret\n")
    try:
        (tmp_path / "linked-secret.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    (tmp_path / "big.bin").write_bytes(b"x" * 1_000_001)
    (tmp_path / ".env.local").write_text("TOKEN=env-local-secret\n")
    (tmp_path / ".npmrc").write_text("//registry.example/:_authToken=npm-secret\n")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("Host hidden-ssh-secret\n")
    output_dir = tmp_path / "run-output"
    state = RunState.create("custom output contextfs", Workspace(tmp_path), run_id="run_custom_output", output_dir=output_dir)
    state.output_dir.mkdir(parents=True, exist_ok=True)

    refresh_contextfs(state)
    refresh_contextfs(state)

    diff = (state.output_dir / "context" / "current_diff.patch").read_text()
    status = (state.output_dir / "context" / "current_status.md").read_text()
    assert "outside-secret" not in diff
    assert "linked-secret.txt" not in diff
    assert "run-output" not in diff
    assert "run-output" not in status
    assert "env-local-secret" not in diff
    assert "npm-secret" not in diff
    assert "hidden-ssh-secret" not in diff
    assert ".env.local" not in status
    assert ".npmrc" not in status
    assert ".ssh" not in status
    assert "big.bin" in diff
    assert "Binary files /dev/null and b/big.bin differ" in diff


def test_context_read_blocks_stale_context_files_not_generated_this_run(tmp_path) -> None:
    state = RunState.create("stale context", Workspace(tmp_path), run_id="run_stale_context")
    stale = state.output_dir / "context" / "shell" / "0001-stale.txt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale-secret\n")
    refresh_contextfs(state)

    result = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "contextfs:context/shell/0001-stale.txt"}), state)

    assert result.ok is False
    assert "not part of the current run recovery surface" in result.output


def test_contextfs_sanitizes_transcript_observations_and_workspace_delta_artifacts(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    outside = tmp_path.parent / "delta-outside-secret.txt"
    outside.write_text("delta-outside-secret\n")
    try:
        (tmp_path / "linked-secret.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    (tmp_path / ".env").write_text("TOKEN=workspace-delta-secret\n")
    (tmp_path / "created.txt").write_text("old\n")
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(
                    tool_calls=(
                        ToolCall(
                            name="shell",
                            args={
                                "cmd": (
                                    f"printf 'visible\\n' > created.txt && {sys.executable} -c "
                                    "\"open('big.bin', 'wb').write(b'x' * 1000001)\""
                                )
                            },
                        ),
                    )
                ),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("workspace delta sanitizer", workspace=tmp_path, run_id="run_delta_sanitizer")

    artifact = next(event.artifact_refs[0] for event in state.events if event.type == "workspace.mutation.detected")
    delta_text = (state.output_dir / artifact).read_text()
    assert "workspace-delta-secret" not in delta_text
    assert "delta-outside-secret" not in delta_text
    assert "linked-secret.txt" not in delta_text
    assert "Binary files /dev/null and" in delta_text

    state.observations.append(
        Observation(
            kind="hook",
            subject=".ssh/config",
            summary="command used TOKEN=secret-value against .ssh/config, .env.local, and artifacts/model-response-0001.json",
            refs=("artifacts/model-response-0001.json",),
            data={
                "cmd": "cat .env.local && curl https://example.com?token=secret-value --config .ssh/config",
                "artifact": "artifacts/model-response-0001.json",
                "path": ".ssh/config",
                "env_path": ".env.local",
            },
        )
    )
    state.transcript.record_tool_call(
        item_id="transcript-tool-call-sanitize",
        turn_id="turn-x",
        model_call_id="model-call-x",
        tool_call_id="call_sanitize",
        tool_name="shell",
        args={"cmd": "cat .env.local && curl https://example.com?token=secret-value --config .ssh/config"},
    )
    refresh_contextfs(state)
    transcript = (state.output_dir / "context" / "transcript.md").read_text()
    observations = (state.output_dir / "context" / "observations.md").read_text()
    for hidden in ("secret-value", "artifacts/model-response-0001", ".ssh", ".env.local", "(hidden).local"):
        assert hidden not in transcript
        assert hidden not in observations


def test_workspace_delta_redacts_preexisting_dirty_tracked_diffs_from_contextfs(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "secret.txt").write_text("clean\n")
    subprocess.run(["git", "add", "secret.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "secret.txt").write_text("dirty-secret\n")

    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git add secret.txt"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("stage dirty file", workspace=tmp_path, run_id="run_dirty_tracked_delta")

    artifact = next(event.artifact_refs[0] for event in state.events if event.type == "workspace.mutation.detected")
    delta_text = (state.output_dir / artifact).read_text()
    assert "dirty-secret" not in delta_text
    assert "full diff redacted" in delta_text
    refresh_contextfs(state)
    copied_diff = (state.output_dir / "context" / "diffs" / "0001-workspace-delta-0001.patch").read_text()
    assert "dirty-secret" not in copied_diff


def test_contextfs_sanitizes_compacted_history(tmp_path) -> None:
    state = RunState.create("compact safety", Workspace(tmp_path), run_id="run_safe_compact")
    state.output_dir.mkdir(parents=True, exist_ok=True)
    artifact = write_text_artifact(state, "context-checkpoint-0001.md", "raw checkpoint", kind="context_checkpoint")
    state.context_checkpoint_artifact = artifact
    state.context_checkpoint = "cmd: curl https://example.com?token=checkpoint-secret\nartifact: artifacts/model-response-0001.json"

    refresh_contextfs(state)
    compacted = (state.output_dir / "context" / "history" / "compacted.md").read_text()
    checkpoint = ContextReadTool().run(ToolCall(name="context_read", args={"ref": f"contextfs:{artifact}"}), state)

    assert "checkpoint-secret" not in compacted
    assert "artifacts/model-response-0001" not in compacted
    assert checkpoint.ok is True


def test_progress_guard_blocks_repeated_failed_command_before_policy_retry(tmp_path) -> None:
    repeated = ToolCall(name="shell", args={"cmd": "false"})
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(repeated,)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "false"}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "false"}),)),
                ModelResponse(content="Command retry was blocked after repeated failures.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("avoid repeated failures", workspace=tmp_path, run_id="run_progress_guard_contract")

    assert state.failed is False
    blocked = state.tool_steps[-1].result
    assert blocked.failure_kind == "progress_blocked"
    assert blocked.data["progress_blocked"] is True
    blocked_call_id = state.tool_steps[-1].call.id
    blocked_event_types = [
        event.type
        for event in state.events
        if event.data.get("tool_call_id") == blocked_call_id and event.type.startswith("tool.execution.")
    ]
    assert blocked_event_types == ["tool.execution.failed", "tool.execution.blocked"]
    assert any(event.type == "contextfs.index.updated" and event.data.get("tool_call_id") == blocked_call_id for event in state.events)
    assert any(observation.kind == "policy_block" for observation in state.observations)


def test_progress_guard_blocks_repeated_same_tool_input_without_mutation(tmp_path) -> None:
    state = RunState.create("avoid read loop", Workspace(tmp_path), run_id="run_read_loop_guard")
    call = ToolCall(name="lookup", args={"key": "hello"})
    state.tool_steps.extend(
        [
            ToolStep(call=call, result=ToolResult(tool_name="lookup", output="hello", ok=True)),
            ToolStep(
                call=ToolCall(name="lookup", args={"key": "hello"}),
                result=ToolResult(tool_name="lookup", output="hello", ok=True),
            ),
        ]
    )

    decision = ProgressGuard().before_tool_call(state, ToolCall(name="lookup", args={"key": "hello"}))

    assert decision.allow is False
    assert "already been returned" in decision.reason


def test_progress_guard_allows_reread_after_context_checkpoint(tmp_path) -> None:
    state = RunState.create("allow reread after compaction", Workspace(tmp_path), run_id="run_read_after_checkpoint")
    state.tool_steps.extend(
        [
            ToolStep(
                call=ToolCall(name="lookup", args={"key": "hello"}),
                result=ToolResult(tool_name="lookup", output="hello", ok=True),
            ),
            ToolStep(
                call=ToolCall(name="lookup", args={"key": "hello"}),
                result=ToolResult(tool_name="lookup", output="hello", ok=True),
            ),
        ]
    )
    state.context_checkpoint_tool_step_count = len(state.tool_steps)

    decision = ProgressGuard().before_tool_call(state, ToolCall(name="lookup", args={"key": "hello"}))

    assert decision.allow is True


def test_extension_host_injects_context_and_registers_visible_tool(tmp_path) -> None:
    class ExtensionHook:
        name = "extension-hook"

        def on_context(self, state: RunState, context: BuiltContext) -> BuiltContext:
            del state
            return replace(context, messages=[*context.messages, Message(role="user", content="extension context")])

    class ExtensionTool:
        name = "ext_tool"
        schema = {"name": "ext_tool", "parameters": {"type": "object", "properties": {}}}

        def run(self, call, state):
            del call, state
            return ToolResult(tool_name=self.name, output="extension tool ok")

    class Extension:
        name = "test-extension"

        def hooks(self):
            return [ExtensionHook()]

        def tools(self):
            return [ExtensionTool()]

    model = RecordingModel(
        [
            ModelResponse(tool_calls=(ToolCall(name="ext_tool"),)),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    state = Kernel(
        model=model,
        profile=ApexCoderProfile(visible_tool_names=("ext_tool",)),
        tools=[],
        policy=AllowAllPolicy(),
        extensions=[Extension()],
        workspace_mode="current",
    ).run("use extension", workspace=tmp_path, run_id="run_extension_host_contract")

    assert state.failed is False
    assert model.messages[0][-1].content == "extension context"
    assert state.tool_steps[0].result.output == "extension tool ok"


def test_context_report_matches_final_model_request_after_hooks(tmp_path) -> None:
    class RequestHook:
        name = "request-hook"

        def on_context(self, state: RunState, context: BuiltContext) -> BuiltContext:
            return replace(context, messages=[*context.messages, Message(role="user", content="hook context")])

        def before_model_call(self, state: RunState, messages, tools):
            return [*messages, Message(role="user", content="before model hook context")], tools[:1]

    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        hooks=[RequestHook()],
        workspace_mode="current",
    ).run("hook context report", workspace=tmp_path, run_id="run_hook_report")

    assert state.failed is False
    started = next(event for event in state.events if event.type == "model.call.started")
    report = json.loads((state.output_dir / started.data["context_report_artifact"]).read_text())
    request = json.loads((state.output_dir / started.data["logical_request_artifact"]).read_text())
    messages = [Message(role=message["role"], content=message["content"]) for message in request["messages"]]
    request_tool_names = {tool["name"] for tool in request["tools"]}
    request_tools = [tool for tool in default_tools() if tool.name in request_tool_names]
    expected_tokens = estimate_messages_tokens(messages) + estimate_tools_tokens(request_tools)
    assert report["token_estimate"] == expected_tokens
    assert request["messages"][-1]["content"] == "before model hook context"


def test_hook_success_events_preserve_order_and_names(tmp_path) -> None:
    seen = {}

    class FirstHook:
        name = "first-hook"

        def on_run_start(self, state: RunState) -> None:
            seen["first"] = state.run_id

    class SecondHook:
        name = 42

        def on_run_start(self, state: RunState) -> None:
            seen["second_after_first"] = seen.get("first") == state.run_id

    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        hooks=[FirstHook(), SecondHook()],
        workspace_mode="current",
    ).run("hook order", workspace=tmp_path, run_id="run_hook_order")

    hook_events = [event for event in state.events if event.type.startswith("hook.")]
    assert [(event.type, event.data) for event in hook_events] == [
        ("hook.started", {"hook": "first-hook", "method": "on_run_start"}),
        ("hook.completed", {"hook": "first-hook", "method": "on_run_start"}),
        ("hook.started", {"hook": "42", "method": "on_run_start"}),
        ("hook.completed", {"hook": "42", "method": "on_run_start"}),
    ]
    assert seen["second_after_first"] is True
    types = [event.type for event in state.events]
    assert types.index("hook.completed") < types.index("run.started")


def test_before_model_call_tuple_return_is_applied_but_list_return_is_ignored(tmp_path) -> None:
    tuple_workspace = tmp_path / "tuple"
    list_workspace = tmp_path / "list"
    tuple_workspace.mkdir()
    list_workspace.mkdir()

    class TupleHook:
        name = "tuple-hook"

        def before_model_call(self, state: RunState, messages, tools):
            return [*messages, Message(role="user", content="tuple hook context")], tools[:1]

    tuple_model = RecordingModel([ModelResponse(content="done", finish_reason="stop")])
    tuple_state = Kernel(
        model=tuple_model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        hooks=[TupleHook()],
        workspace_mode="current",
    ).run("tuple hook", workspace=tuple_workspace, run_id="run_tuple_hook")

    assert tuple_state.failed is False
    assert tuple_model.messages[0][-1].content == "tuple hook context"

    class ListHook:
        name = "list-hook"

        def before_model_call(self, state: RunState, messages, tools):
            return [[*messages, Message(role="user", content="list hook context")], tools[:1]]

    list_model = RecordingModel([ModelResponse(content="done", finish_reason="stop")])
    list_state = Kernel(
        model=list_model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        hooks=[ListHook()],
        workspace_mode="current",
    ).run("list hook", workspace=list_workspace, run_id="run_list_hook")

    assert list_state.failed is False
    assert all(message.content != "list hook context" for message in list_model.messages[0])


def test_hook_error_policy_record_continues_without_hook_completed(tmp_path) -> None:
    class FailingHook:
        name = "failing-record-hook"

        def before_model_call(self, state: RunState, messages, tools):
            raise RuntimeError("recorded hook failed")

    class LaterHook:
        name = "later-hook"

        def before_model_call(self, state: RunState, messages, tools):
            return [*messages, Message(role="user", content="later hook ran")], tools

    model = RecordingModel([ModelResponse(content="done", finish_reason="stop")])
    state = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        hooks=[FailingHook(), LaterHook()],
        hook_error_policy="record",
        workspace_mode="current",
    ).run("record hook failure", workspace=tmp_path, run_id="run_hook_record")

    hook_events = [(event.type, event.data["hook"], event.data["method"]) for event in state.events if event.type.startswith("hook.")]
    assert state.failed is False
    assert "later hook ran" in [message.content for message in model.messages[0]]
    assert ("hook.failed", "failing-record-hook", "before_model_call") in hook_events
    assert ("hook.completed", "failing-record-hook", "before_model_call") not in hook_events
    assert ("hook.completed", "later-hook", "before_model_call") in hook_events


def test_after_model_response_hook_failure_fails_current_model_call(tmp_path) -> None:
    class FailingHook:
        name = "after-model-failing-hook"

        def after_model_response(self, state: RunState, response: ModelResponse) -> ModelResponse:
            raise RuntimeError("after model failed")

    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="should fail", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        hooks=[FailingHook()],
        workspace_mode="current",
    ).run("after model failure", workspace=tmp_path, run_id="run_after_model_hook_fail")

    types = [event.type for event in state.events]
    assert state.failed is True
    assert "model.call.started" in types
    assert "model.call.failed" in types
    assert "run.failed" in types
    assert types.index("hook.failed") < types.index("model.call.failed")
    failed = next(event for event in state.events if event.type == "model.call.failed")
    assert failed.data["reason"] == "hook after-model-failing-hook.after_model_response failed: after model failed"


def test_before_finish_hook_receives_profile_decision_and_can_override(tmp_path) -> None:
    class AllowFinishHook:
        name = "allow-finish-hook"

        def before_finish(self, state: RunState, response: ModelResponse, decision):
            assert decision.allow is False
            return type(decision).allowed()

    call = ToolCall(name="shell", args={"cmd": "false"})
    state = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(call,)), ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        hooks=[AllowFinishHook()],
        workspace_mode="current",
    ).run("override finish decision", workspace=tmp_path, run_id="run_before_finish_override")

    assert state.failed is False
    assert state.final_output == "done"
    assert any(event.type == "hook.completed" and event.data["method"] == "before_finish" for event in state.events)


def test_initial_model_context_includes_contextfs_index(tmp_path) -> None:
    model = RecordingModel([ModelResponse(content="done", finish_reason="stop")])
    state = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("read contextfs first", workspace=tmp_path, run_id="run_initial_contextfs")

    assert state.failed is False
    first_request = model.messages[0]
    contextfs = next(message for message in first_request if message.meta.get("context_layer") == "contextfs_index")
    assert "context/task.md" in contextfs.content
    assert ".tinyagent/runs/run_initial_contextfs" not in contextfs.content


def test_finish_gate_blocks_edit_without_diff_or_verification(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.txt",
            "@@",
            "-hello",
            "+hello updated",
            "*** End Patch",
        ]
    )
    kernel = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    )

    state = kernel.run("edit then finish too early", workspace=tmp_path, run_id="run_finish_gate_contract")

    assert state.failed is True
    blocked = next(event for event in state.events if event.type == "finish.blocked")
    assert "inspect changed files" in blocked.data["reason"]


def test_workspace_delta_detects_shell_mutation_and_blocks_early_finish(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(
                    tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('generated.txt', 'w').write('x')\""}),)
                ),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("generate a file", workspace=tmp_path, run_id="run_shell_delta")

    assert any(event.type == "workspace.mutation.detected" for event in state.events)
    assert any(event.type == "file.changed" and event.data["path"] == "generated.txt" for event in state.events)
    assert any(observation.kind == "file_changed" and observation.subject == "generated.txt" for observation in state.observations)
    blocked = next(event for event in state.events if event.type == "finish.blocked")
    assert "inspect changed files" in blocked.data["reason"]


def test_workspace_delta_shell_mutation_read_file_inspection_can_finish(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(
                    tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('generated.txt', 'w').write('x')\""}),)
                ),
                ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "generated.txt"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("generate and inspect a file", workspace=tmp_path, run_id="run_shell_delta_read_file")

    assert state.failed is False


def test_workspace_delta_ignores_contextfs_writes_for_read_only_tools(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "hello.txt"}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("read only", workspace=tmp_path, run_id="run_read_only_delta")

    assert state.failed is False
    assert not any(event.type == "workspace.mutation.detected" for event in state.events)
    assert not any(event.type in {"diff.snapshot", "file.changed"} for event in state.events)


def test_non_mutating_shell_dispatch_records_boundaries_without_detected_mutation(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "printf ok"}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("non-mutating shell", workspace=tmp_path, run_id="run_shell_no_delta")

    assert state.failed is False
    assert any(event.type == "workspace.mutation.planned" for event in state.events)
    assert any(event.type == "workspace.mutation.started" for event in state.events)
    assert any(event.type == "workspace.mutation.completed" for event in state.events)
    assert any(event.type == "workspace.delta.started" for event in state.events)
    assert any(event.type == "workspace.delta.completed" for event in state.events)
    assert not any(event.type == "workspace.mutation.detected" for event in state.events)
    assert not any(event.type in {"diff.snapshot", "file.changed"} for event in state.events)


def test_workspace_delta_detects_edit_to_existing_untracked_git_file(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "notes.txt").write_text("before\n")
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(
                    tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('notes.txt', 'w').write('after')\""}),)
                ),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("edit existing untracked file", workspace=tmp_path, run_id="run_untracked_delta")

    assert any(event.type == "file.changed" and event.data["path"] == "notes.txt" for event in state.events)
    mutation = next(event for event in state.events if event.type == "workspace.mutation.detected")
    artifact = mutation.artifact_refs[0]
    assert "Modified pre-existing untracked file" in (state.output_dir / artifact).read_text()


def test_workspace_delta_does_not_attribute_preexisting_dirty_git_files(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "dirty.txt").write_text("dirty before\n")
    (tmp_path / "new.txt").write_text("new before\n")
    subprocess.run(["git", "add", "dirty.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "dirty.txt").write_text("dirty after\n")
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(
                    tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('new.txt', 'w').write('new after')\""}),)
                ),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("edit only new file", workspace=tmp_path, run_id="run_dirty_attribution")

    changed = [event.data["path"] for event in state.events if event.type == "file.changed"]
    assert "new.txt" in changed
    assert "dirty.txt" not in changed


def test_workspace_delta_detects_clean_to_clean_git_checkout(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "mode.txt").write_text("one\n")
    subprocess.run(["git", "add", "mode.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "one"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    trunk = subprocess.run(["git", "branch", "--show-current"], cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "checkout", "-b", "other"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "mode.txt").write_text("two\n")
    subprocess.run(["git", "add", "mode.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "two"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "checkout", trunk], cwd=tmp_path, check=True, capture_output=True, text=True)

    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git checkout other"}),)),
                ModelResponse(content="Switched branches.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("checkout branch", workspace=tmp_path, run_id="run_clean_checkout_delta")

    assert any(event.type == "file.changed" and event.data["path"] == "mode.txt" for event in state.events)


def test_workspace_delta_handles_non_git_to_git_transition(tmp_path) -> None:
    (tmp_path / "keep.txt").write_text("keep\n")
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(
                    tool_calls=(
                        ToolCall(
                            name="shell",
                            args={"cmd": f"git init && {sys.executable} -c \"open('created.txt', 'w').write('created')\""},
                        ),
                    )
                ),
                ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "created.txt"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("initialize git and create a file", workspace=tmp_path, run_id="run_git_transition_delta")

    changed = [event.data["path"] for event in state.events if event.type == "file.changed"]
    assert "created.txt" in changed
    assert "keep.txt" not in changed


def test_workspace_delta_detects_pure_git_init_transition(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git init"}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("initialize git only", workspace=tmp_path, run_id="run_pure_git_init_delta")

    mutation = next(event for event in state.events if event.type == "workspace.mutation.detected")
    assert mutation.data["paths"] == []
    assert "non-git -> git" in (state.output_dir / mutation.artifact_refs[0]).read_text()
    assert any("inspect changed files" in event.data["reason"] for event in state.events if event.type == "finish.blocked")


def test_workspace_delta_detects_pure_git_removal_transition(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "rm -rf .git"}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=AllowAllPolicy(),
        workspace_mode="current",
    ).run("remove git metadata", workspace=tmp_path, run_id="run_pure_git_remove_delta")

    mutation = next(event for event in state.events if event.type == "workspace.mutation.detected")
    assert mutation.data["paths"] == []
    assert "git -> non-git" in (state.output_dir / mutation.artifact_refs[0]).read_text()


def test_workspace_delta_detects_git_mode_only_mutation(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "tracked.sh").write_text("#!/bin/sh\necho hi\n")
    subprocess.run(["git", "add", "tracked.sh"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "chmod +x tracked.sh"}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff --summary -- tracked.sh"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("chmod a tracked file", workspace=tmp_path, run_id="run_mode_delta")

    assert any(event.type == "file.changed" and event.data["path"] == "tracked.sh" for event in state.events)


def test_workspace_delta_detects_git_index_only_mutation(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("one\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (tmp_path / "tracked.txt").write_text("two\n")

    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git add tracked.txt"}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff --cached -- tracked.txt"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("stage a dirty file", workspace=tmp_path, run_id="run_index_delta")

    assert any(event.type == "file.changed" and event.data["path"] == "tracked.txt" for event in state.events)


def test_workspace_delta_detects_existing_untracked_directory_file_change(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "draft.txt").write_text("before\n")

    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(
                    tool_calls=(
                        ToolCall(
                            name="shell",
                            args={"cmd": f"{sys.executable} -c \"open('notes/draft.txt', 'w').write('after')\""},
                        ),
                    )
                ),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff -- notes/draft.txt"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("edit a file inside an existing untracked dir", workspace=tmp_path, run_id="run_untracked_dir_delta")

    assert any(event.type == "file.changed" and event.data["path"] == "notes/draft.txt" for event in state.events)


def test_workspace_delta_ignores_common_generated_artifacts(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(
                    tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('.coverage', 'w').write('data')\""}),)
                ),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("write generated test artifact", workspace=tmp_path, run_id="run_generated_artifact_delta")

    assert state.failed is False
    assert not any(event.type == "workspace.mutation.detected" for event in state.events)


def test_workspace_delta_ignores_secret_paths_in_non_git_workspaces(tmp_path) -> None:
    state = RunState.create("write local secrets", Workspace(tmp_path), run_id="run_secret_delta")
    observer = WorkspaceDeltaObserver()
    before = observer.snapshot(state)
    (tmp_path / ".env.local").write_text("TOKEN=secret\n")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("Host secret\n")
    after = observer.snapshot(state)

    delta = observer.diff(state, before, after, ToolCall(id="call_secret", name="shell", args={}))

    assert delta.mutated is False
    assert not state.events


def test_workspace_delta_handles_output_dir_outside_workspace(tmp_path) -> None:
    output_dir = tmp_path.parent / "outside-delta-output"
    output_dir.mkdir()
    state = RunState.create("outside output delta", Workspace(tmp_path), run_id="run_outside_delta", output_dir=output_dir)
    observer = WorkspaceDeltaObserver()
    before = observer.snapshot(state)
    (output_dir / "events.jsonl").write_text("trace\n")
    (tmp_path / "generated.txt").write_text("generated\n")
    after = observer.snapshot(state)

    delta = observer.diff(state, before, after, ToolCall(id="call_generated", name="shell", args={}))

    assert delta.mutated is True
    assert delta.paths == ("generated.txt",)


def _write_root_output_user_neighbors_and_expected_paths(root) -> tuple[str, ...]:
    (root / "generated.txt").write_text("generated\n")
    (root / "artifacts.txt").write_text("user artifact neighbor\n")
    (root / "contextual").mkdir()
    (root / "contextual" / "file.txt").write_text("user context neighbor\n")
    (root / "metrics.json.bak").write_text("user metrics neighbor\n")
    return ("artifacts.txt", "contextual/file.txt", "generated.txt", "metrics.json.bak")


def test_workspace_delta_detects_git_mutation_when_output_dir_is_workspace_root(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    state = RunState.create("root output delta", Workspace(tmp_path), run_id="run_root_output_delta", output_dir=tmp_path)
    observer = WorkspaceDeltaObserver()
    before = observer.snapshot(state)
    user_paths = _write_root_output_user_neighbors_and_expected_paths(tmp_path)
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "trace.txt").write_text("trace\n")
    after = observer.snapshot(state)

    delta = observer.diff(state, before, after, ToolCall(id="call_generated", name="shell", args={}))

    assert delta.mutated is True
    assert delta.paths == user_paths


def test_workspace_delta_detects_non_git_mutation_when_output_dir_is_workspace_root(tmp_path) -> None:
    state = RunState.create("root output non git delta", Workspace(tmp_path), run_id="run_root_output_non_git_delta", output_dir=tmp_path)
    observer = WorkspaceDeltaObserver()
    before = observer.snapshot(state)
    user_paths = _write_root_output_user_neighbors_and_expected_paths(tmp_path)
    (tmp_path / "context").mkdir()
    (tmp_path / "context" / "INDEX.md").write_text("context\n")
    (tmp_path / "events.jsonl").write_text("trace\n")
    after = observer.snapshot(state)

    delta = observer.diff(state, before, after, ToolCall(id="call_generated", name="shell", args={}))

    assert delta.mutated is True
    assert delta.paths == user_paths


def test_failed_shell_mutation_still_requires_mutation_gates(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(
                    tool_calls=(
                        ToolCall(
                            name="shell", args={"cmd": f"{sys.executable} -c \"open('failed.txt', 'w').write('x'); raise SystemExit(1)\""}
                        ),
                    )
                ),
                ModelResponse(content="Command failed.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("failed mutation", workspace=tmp_path, run_id="run_failed_mutation")

    blocked = [event.data["reason"] for event in state.events if event.type == "finish.blocked"]
    assert any("inspect changed files" in reason for reason in blocked)


def test_eval_metrics_do_not_count_same_mutating_shell_diff_as_post_edit(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "tracked.txt").write_text("one\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(
                    tool_calls=(
                        ToolCall(
                            name="shell",
                            args={"cmd": f"{sys.executable} -c \"open('tracked.txt', 'w').write('two')\"; git diff -- tracked.txt"},
                        ),
                    )
                ),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("mutate and inspect in one shell command", workspace=tmp_path, run_id="run_same_command_diff_metric")

    metrics = extract_run_metrics(state.output_dir)
    assert metrics.diff_after_edit is False


def test_non_git_finish_gate_accepts_changed_file_inspection(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.txt",
            "@@",
            "-hello",
            "+hello updated",
            "*** End Patch",
        ]
    )
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "sed -n '1,120p' hello.txt"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("edit non-git", workspace=tmp_path, run_id="run_non_git_finish")

    assert state.failed is False


def test_non_git_finish_gate_accepts_read_file_changed_file_inspection(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.txt",
            "@@",
            "-hello",
            "+hello updated",
            "*** End Patch",
        ]
    )
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "hello.txt"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("edit non-git and inspect with read_file", workspace=tmp_path, run_id="run_non_git_read_file_finish")

    assert state.failed is False


def test_git_status_alone_does_not_satisfy_post_edit_finish_gate(tmp_path) -> None:
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
            "+hello updated",
            "*** End Patch",
        ]
    )
    kernel = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git status --short"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    )

    state = kernel.run("edit, status, finish", workspace=tmp_path, run_id="run_status_not_diff")

    assert state.failed is True
    blocked = next(event for event in state.events if event.type == "finish.blocked")
    assert "inspect git diff" in blocked.data["reason"]


def test_declarative_policy_metadata_and_repeated_command_guard(tmp_path) -> None:
    state = RunState.create("policy", Workspace(tmp_path), run_id="run_policy")
    policy = LocalPolicy()
    network = policy.evaluate(ToolCall(name="shell", args={"cmd": "curl https://example.com"}), state)
    assert network.kind == "deny"
    assert network.permission == "network"
    assert network.matched_rule == "network:*:deny"

    failed = ToolResult(tool_name="shell", output="failed", ok=False)
    cmd = "false"
    state.tool_steps.extend(
        [
            ToolStep(ToolCall(name="shell", args={"cmd": cmd}), failed),
            ToolStep(ToolCall(name="shell", args={"cmd": cmd}), failed),
        ]
    )
    repeated = policy.evaluate(ToolCall(name="shell", args={"cmd": cmd}), state)
    assert repeated.kind == "deny"
    assert repeated.matched_rule == "bash.repeated_failed_command"

    allow_network_config = PolicyConfig(
        default="deny",
        rules=(PolicyRule("network", "*", "allow"), PolicyRule("bash", "*", "allow")),
    )
    allowed_network = LocalPolicy(config=allow_network_config).evaluate(
        ToolCall(name="shell", args={"cmd": "curl https://example.com"}),
        state,
    )
    assert allowed_network.kind == "allow"
    assert allowed_network.permission == "network"
    assert allowed_network.matched_rule == "network:*:allow"


def test_policy_blocks_relative_redirect_workspace_escape(tmp_path) -> None:
    state = RunState.create("policy", Workspace(tmp_path), run_id="run_policy_redirect")
    decision = LocalPolicy().evaluate(ToolCall(name="shell", args={"cmd": "printf x > ../outside.txt"}), state)

    assert decision.kind == "needs_approval"
    assert decision.permission == "external_directory"


def test_policy_blocks_output_dir_evidence_writes_outside_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output_dir = tmp_path / "run-output"
    state = RunState.create("policy", Workspace(workspace), run_id="run_policy_output", output_dir=output_dir)
    target = output_dir / "context" / "history" / "raw.jsonl"

    decision = LocalPolicy().evaluate(ToolCall(name="shell", args={"cmd": f"printf x > {target}"}), state)

    assert decision.kind == "deny"
    assert decision.permission == "run_artifact_write"


def test_contextfs_read_hints_quote_paths_with_spaces() -> None:
    hints = read_hints("/tmp/tiny agent/context/output file.txt", failure=True)

    assert hints[0] == "tail -120 '/tmp/tiny agent/context/output file.txt'"
    assert hints[1] == "rg \"FAILED|ERROR|Traceback|AssertionError\" '/tmp/tiny agent/context/output file.txt'"


def test_policy_blocks_common_env_path_variants(tmp_path) -> None:
    state = RunState.create("policy", Workspace(tmp_path), run_id="run_policy_env")
    policy = LocalPolicy()
    for cmd in ("cat ./.env", "cat config/.env", f"{sys.executable} -c 'open(\".env\").read()'"):
        decision = policy.evaluate(ToolCall(name="shell", args={"cmd": cmd}), state)
        assert decision.kind == "deny"
        assert decision.permission == "secrets"


def test_eval_metrics_count_policy_denial_once(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "curl https://example.com"}),)),
                ModelResponse(content="Network command was denied by policy.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
        approval_mode="never",
    ).run("deny network", workspace=tmp_path, run_id="run_policy_metric_once")

    metrics = extract_run_metrics(state.output_dir)
    assert metrics.policy_denials == 1
    assert metrics.tool_error_count == 1
    assert metrics.tool_error_kinds["policy_denied"] == 1
    assert "unknown" not in metrics.tool_error_kinds
    assert metrics.mcp_call_count == 0


def test_eval_metrics_count_attempted_context_tools_before_execution(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="context_search", args={"query": "hello"}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("attempt context search", workspace=tmp_path, run_id="run_attempt_context_metric")

    metrics = extract_run_metrics(state.output_dir)
    assert metrics.context_search_count == 1


def test_eval_metrics_treat_structured_reads_as_pre_edit_inspection(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.txt",
            "@@",
            "-hello",
            "+hello updated",
            "*** End Patch",
        ]
    )
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "hello.txt"}),)),
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
        budgets=RunBudgets(max_model_calls=3),
    ).run("read then edit", workspace=tmp_path, run_id="run_structured_inspection_metric")

    metrics = extract_run_metrics(state.output_dir)
    assert metrics.inspected_before_edit is True
    assert metrics.diff_after_edit is False
    assert metrics.verification_after_edit is False


def test_noncritical_stable_context_respects_budget(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "AGENTS.md").write_text("project instruction\n" * 200)
    state = RunState.create("budget context", Workspace(tmp_path), run_id="run_context_budget")
    profile = ApexCoderProfile(context_config=ContextConfig(compact_at_tokens=20, max_recent_tool_tokens=1))

    built = profile.build_context(state)

    assert any(item.id == "system:profile" for item in built.included)
    assert any(item.id == "task:current" for item in built.included)
    assert any(exclusion.item_id == "project:instructions" for exclusion in built.excluded)


def test_container_sandbox_mode_fails_setup_until_backend_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tinyagent.core.workspace.detect_container_backend", lambda: None)
    kernel = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        sandbox_mode="container",
    )

    with pytest.raises(ValueError, match="requires a usable Docker or Podman backend"):
        kernel.run("use container sandbox", workspace=tmp_path, run_id="run_container_sandbox")


def test_container_sandbox_mode_records_enforced_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tinyagent.core.workspace.detect_container_backend", lambda: "docker")
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        sandbox_mode="container",
    ).run("use container sandbox", workspace=tmp_path, run_id="run_container_sandbox")

    boundary = next(event for event in state.events if event.type == "workspace.boundary")
    assert boundary.data["sandbox_mode"] == "container"
    assert boundary.data["sandbox_backend"] == "docker"
    assert boundary.data["network_mode"] == "deny"
    assert boundary.data["sandbox_enforced"] is True
    preflight = next(event for event in state.events if event.type == "shell.preflight.completed")
    assert preflight.data["authoritative"] is False
    assert preflight.data["scope"] == "host-preflight-for-container"


def test_native_sandbox_mode_fails_setup_until_backend_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tinyagent.core.workspace.detect_native_backend", lambda: None)
    kernel = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        sandbox_mode="native",
    )

    with pytest.raises(ValueError, match="requires a supported native sandbox backend"):
        kernel.run("use native sandbox", workspace=tmp_path, run_id="run_native_sandbox")


def test_native_sandbox_mode_records_enforced_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tinyagent.core.workspace.detect_native_backend", lambda: "seatbelt")
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        sandbox_mode="native",
    ).run("use native sandbox", workspace=tmp_path, run_id="run_native_sandbox")

    boundary = next(event for event in state.events if event.type == "workspace.boundary")
    assert boundary.data["sandbox_mode"] == "native"
    assert boundary.data["sandbox_backend"] == "seatbelt"
    assert boundary.data["network_mode"] == "deny"
    assert boundary.data["sandbox_enforced"] is True
    preflight = next(event for event in state.events if event.type == "shell.preflight.completed")
    assert preflight.data["authoritative"] is False
    assert preflight.data["scope"] == "host-preflight-for-native-sandbox"


def test_shell_execution_envelope_exposes_sandbox_contract(tmp_path) -> None:
    state = RunState.create("contract", Workspace(tmp_path), run_id="run_shell_contract")
    result = ShellTool().run(ToolCall(name="shell", args={"cmd": "printf ok"}), state)

    envelope = result.metadata["execution_envelope"]
    assert envelope["read_roots"] == [str(tmp_path)]
    assert str(tmp_path) in envelope["writable_roots"]
    assert str(state.output_dir / "home") in envelope["writable_roots"]
    assert envelope["network_mode"] == "deny"
    assert envelope["sandbox_backend"] == "none"
    assert envelope["sandbox_enforced"] is False
    assert "escalation_hint" in envelope


def test_shell_execution_envelope_exposes_native_sandbox_contract(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("tinyagent.core.execution.native_backend_version", lambda backend: "sandbox-exec" if backend == "seatbelt" else "")
    state = RunState.create("contract", Workspace(tmp_path), run_id="run_native_contract")
    state.workspace_envelope = WorkspaceEnvelope(
        root=tmp_path,
        original_root=tmp_path,
        mode="current",
        effective_mode="current",
        allowed_roots=(tmp_path,),
        sandbox_mode="native",
        sandbox_backend="seatbelt",
        network_mode="deny",
        sandbox_enforced=True,
    )

    envelope = build_execution_envelope(state, timeout_seconds=10).to_json_dict()
    assert envelope["sandbox_backend"] == "seatbelt"
    assert envelope["sandbox_backend_version"] == "sandbox-exec"
    assert envelope["sandbox_enforced"] is True
    assert envelope["container_image"] == ""
    assert "Native shell sandbox is active" in envelope["escalation_hint"]


def test_shell_container_sandbox_wraps_process_with_isolated_home_and_network(tmp_path) -> None:
    from tinyagent.core.tools.builtins.shell import _popen_command

    home = tmp_path / "run" / "container-home"
    envelope = SimpleNamespace(
        sandbox_enforced=True,
        sandbox_backend="docker",
        container_home_host=home,
        container_image="python:3.12-slim",
        cwd=tmp_path,
        network_mode="deny",
    )

    launch = _popen_command("printf ok", envelope, "call/one")
    argv = launch.args

    assert launch.shell is False
    assert home.exists()
    assert launch.cidfile == tmp_path / "run" / "container-cids" / "call-one.cid"
    assert argv[:2] == ["docker", "run"]
    assert "--pull" in argv
    assert "never" in argv
    assert "--cidfile" in argv
    assert str(launch.cidfile) in argv
    assert "--user" in argv
    assert "--network" in argv
    assert "none" in argv
    assert f"{tmp_path}:/workspace:rw" in argv
    assert f"{home}:/home/tinyagent:rw" in argv
    assert "--tmpfs" in argv
    assert "/workspace/.tinyagent:rw,noexec,nosuid,size=64m" in argv
    assert "HOME=/home/tinyagent" in argv
    assert "git config --global --add safe.directory /workspace" in argv[-1]
    assert argv[-1].endswith("printf ok")


def test_shell_native_sandbox_wraps_process_with_seatbelt_profile(tmp_path) -> None:
    from tinyagent.core.tools.builtins.shell import _popen_command

    envelope = SimpleNamespace(
        sandbox_enforced=True,
        sandbox_backend="seatbelt",
        cwd=tmp_path,
        read_roots=(tmp_path,),
        writable_roots=(tmp_path, tmp_path / "home"),
        denied_paths=(tmp_path / ".tinyagent" / "runs" / "run" / "artifacts",),
        network_mode="deny",
    )

    launch = _popen_command("printf ok", envelope, "call/one")
    argv = launch.args

    assert launch.shell is False
    assert argv[:2] == ["sandbox-exec", "-p"]
    assert argv[-3:] == ["/bin/sh", "-c", "printf ok"]
    assert "(deny network*)" in argv[2]
    assert "(allow file-read*)" not in argv[2]
    assert f'(allow file-read* (subpath "{tmp_path.resolve()}"))' in argv[2]
    assert str(tmp_path) in argv[2]


def test_native_backend_detection_requires_seatbelt_probe(monkeypatch) -> None:
    import tinyagent.core.native_sandbox as native_sandbox

    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(native_sandbox.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(native_sandbox.shutil, "which", lambda name: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None)
    monkeypatch.setattr(native_sandbox.subprocess, "run", fake_run)

    assert native_sandbox.detect_native_backend() is None
    assert calls


def test_shell_container_timeout_kills_cidfile_container(tmp_path, monkeypatch) -> None:
    from tinyagent.core.tools.builtins.shell import _ProcessLaunch, _terminate_container

    cidfile = tmp_path / "container.cid"
    cidfile.write_text("abc123\n")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("tinyagent.core.tools.builtins.shell.subprocess.run", fake_run)

    _terminate_container(_ProcessLaunch(args=["docker"], shell=False, container_backend="docker", cidfile=cidfile))

    assert calls == [["docker", "kill", "abc123"], ["docker", "rm", "-f", "abc123"]]


def test_container_image_rejects_option_like_values(monkeypatch) -> None:
    from tinyagent.core.container_sandbox import default_container_image

    monkeypatch.setenv("TINYAGENT_CONTAINER_IMAGE", "--privileged")

    with pytest.raises(ValueError, match="cannot start with"):
        default_container_image()


def test_policy_and_sandbox_denials_have_distinct_failure_dimensions(tmp_path) -> None:
    network_call = ToolCall(name="shell", args={"cmd": "curl https://example.com"})
    policy_state = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(network_call,)), ModelResponse(content="blocked", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
        approval_mode="never",
    ).run("deny network", workspace=tmp_path, run_id="run_policy_dimensions")

    policy_result = policy_state.tool_results[0]
    assert policy_result.failure_kind == "policy_denied"
    assert policy_result.data["capability"] == "network"
    assert policy_result.data["source"] == "policy"
    assert any(observation.kind == "policy_block" and observation.data["source"] == "policy" for observation in policy_state.observations)

    class SandboxBlockingHook:
        name = "sandbox-blocking-hook"

        def before_tool_call(self, state, call, decision):
            del state, decision
            return ToolResult(
                tool_name=call.name,
                call_id=call.id,
                output="sandbox blocked command: network denied. Request approval or choose an offline path.",
                ok=False,
                data={
                    "blocked": True,
                    "failure_kind": "sandbox_blocked",
                    "capability": "network",
                    "source": "sandbox",
                    "recoverability": "request_approval",
                },
                failure_kind="sandbox_blocked",
            )

    sandbox_state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "printf x"}),)),
                ModelResponse(content="blocked", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=AllowAllPolicy(),
        hooks=[SandboxBlockingHook()],
        workspace_mode="current",
    ).run("synthetic sandbox block", workspace=tmp_path, run_id="run_sandbox_dimensions")

    sandbox_result = sandbox_state.tool_results[0]
    assert sandbox_result.failure_kind == "sandbox_blocked"
    assert sandbox_result.data["source"] == "sandbox"
    assert any(
        observation.kind == "sandbox_block" and observation.data["source"] == "sandbox" for observation in sandbox_state.observations
    )


def test_approval_denial_preserves_original_capability(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "printf x > ../outside.txt"}),)),
                ModelResponse(content="blocked", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        approval_mode="never",
        workspace_mode="current",
    ).run("deny workspace escape approval", workspace=tmp_path, run_id="run_approval_capability")

    result = state.tool_results[0]
    assert result.failure_kind == "policy_denied"
    assert result.data["capability"] == "external_directory"
    assert result.data["source"] == "policy"


def test_final_contextfs_raw_history_includes_run_completion(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        workspace_mode="current",
    ).run("final contextfs", workspace=tmp_path, run_id="run_final_contextfs")

    raw = (state.output_dir / "context" / "history" / "raw.jsonl").read_text()
    assert '"type": "run.completed"' in raw


def test_hook_can_inject_context_and_block_tool(tmp_path) -> None:
    class FirstBlockingHook:
        name = "first-blocking-hook"

        def on_context(self, state: RunState, context: BuiltContext) -> BuiltContext:
            return replace(context, messages=[*context.messages, Message(role="user", content="hook context")])

        def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolResult:
            return ToolResult(tool_name=call.name, call_id=call.id, output="hook blocked", ok=False, failure_kind="policy_denied")

    class SecondHook:
        name = "second-hook"

        def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolCall:
            raise AssertionError("second hook should not run after ToolResult")

    call = ToolCall(name="shell", args={"cmd": "printf should-not-run"})
    state = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(call,)), ModelResponse(content="blocked by hook", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=[ShellTool()],
        policy=workspace_shell_policy(),
        hooks=[FirstBlockingHook(), SecondHook()],
        workspace_mode="current",
    ).run("hook test", workspace=tmp_path, run_id="run_hook_contract")

    assert state.failed is False
    assert "command.started" not in [event.type for event in state.events]
    assert any(event.type == "hook.completed" and event.data["method"] == "on_context" for event in state.events)
    assert any(event.type == "tool.execution.blocked" for event in state.events)
    assert not any(event.type == "tool.execution.started" for event in state.events)
    assert not any(event.type == "approval.requested" for event in state.events)
    assert not any(event.type.startswith("hook.") and event.data.get("hook") == "second-hook" for event in state.events)
    first_context = next(event for event in state.events if event.type == "model.call.started")
    assert "hook context" in (state.output_dir / first_context.data["context_artifact"]).read_text()


def test_hook_mutated_tool_call_is_rechecked_by_policy(tmp_path) -> None:
    seen_by_later_hook = {}

    class MutatingHook:
        name = "mutating-hook"

        def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolCall:
            assert decision.allowed is True
            return ToolCall(name="shell", args={"cmd": "curl https://example.com"}, id=call.id)

    class LaterHook:
        name = "later-hook"

        def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> None:
            seen_by_later_hook["tool"] = call.name
            seen_by_later_hook["cmd"] = call.args["cmd"]
            seen_by_later_hook["decision_allowed"] = decision.allowed
            return None

    call = ToolCall(name="shell", args={"cmd": "git diff -- README.md"})
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(call,)),
                ModelResponse(content="Network command was denied by policy.", finish_reason="stop"),
                ModelResponse(content="Network command was denied by policy.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        hooks=[MutatingHook(), LaterHook()],
        workspace_mode="current",
        approval_mode="never",
    ).run("mutate tool", workspace=tmp_path, run_id="run_hook_policy_recheck")

    assert state.failed is False
    assert seen_by_later_hook == {"tool": "shell", "cmd": "curl https://example.com", "decision_allowed": True}
    assert "command.started" not in [event.type for event in state.events]
    decisions = [event for event in state.events if event.type == "policy.evaluated"]
    assert [decision.data["kind"] for decision in decisions] == ["allow", "deny"]
    assert decisions[-1].data["permission"] == "network"


def test_equal_tool_call_return_from_hook_does_not_trigger_policy_reevaluation(tmp_path) -> None:
    class EqualReturnHook:
        name = "equal-return-hook"

        def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolCall:
            return replace(call)

    call = ToolCall(name="shell", args={"cmd": "pwd"})
    state = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(call,)), ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        hooks=[EqualReturnHook()],
        workspace_mode="current",
    ).run("equal hook return", workspace=tmp_path, run_id="run_equal_hook_return")

    assert state.failed is False
    decisions = [event for event in state.events if event.type == "policy.evaluated"]
    assert len(decisions) == 1
    assert decisions[0].data["kind"] == "allow"


def test_hook_failure_fails_closed_by_default(tmp_path) -> None:
    class FailingHook:
        name = "failing-hook"

        def before_model_call(self, state: RunState, messages, tools):
            raise RuntimeError("mandatory hook failed")

    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="should not run", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
        hooks=[FailingHook()],
        workspace_mode="current",
    ).run("hook failure", workspace=tmp_path, run_id="run_hook_fail_closed")

    assert state.failed is True
    assert "mandatory hook failed" in (state.failure_reason or "")
    assert any(event.type == "hook.failed" for event in state.events)
    assert not any(event.type == "model.call.started" for event in state.events)


def test_sdk_streams_same_durable_events_as_run_log(tmp_path) -> None:
    async def collect():
        agent = Agent.create(
            workspace=tmp_path,
            provider=FakeModelProvider([ModelResponse(content="sdk done", finish_reason="stop")]),
            tools=default_tools(),
            policy=workspace_shell_policy(),
        )
        return [event async for event in agent.run("sdk task", run_id="run_sdk_contract")]

    events = asyncio.run(collect())
    run_dir = tmp_path / ".tinyagent" / "runs" / "run_sdk_contract"
    persisted = [json.loads(line)["id"] for line in (run_dir / "events.jsonl").read_text().splitlines() if line]
    assert [event.id for event in events if event.durability == "event_log"] == persisted


def test_run_graph_fork_metadata_and_eval_thresholds(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=workspace_shell_policy(),
    ).run("fork me", workspace=tmp_path, run_id="run_fork_source")

    destination = fork_run(state.output_dir, "0001", output_dir=tmp_path / "forked")
    metadata = json.loads((destination / "fork.json").read_text())
    assert metadata["parent_run_id"] == state.run_id
    assert metadata["parent_event_seq"] == 1

    metrics = extract_run_metrics(state.output_dir)
    assert metrics.tool_error_count == 0
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(json.dumps({"min_solve_rate": 1.0, "max_policy_denials": 0, "max_unknown_errors": 0}))
    passing = evaluate_thresholds([{"success": True, "policy_denials": 0, "tool_error_kinds": {}}], thresholds)
    assert passing == []
