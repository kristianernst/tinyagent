from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest

from agentd.context import BuiltContext, ContextConfig, estimate_messages_tokens, estimate_tools_tokens
from agentd.contextfs import read_hints, refresh_contextfs
from agentd.eval_metrics import evaluate_thresholds, extract_run_metrics
from agentd.kernel import Kernel
from agentd.models import FakeModelProvider
from agentd.observations import Observation
from agentd.output import write_text_artifact
from agentd.policy import LocalPolicy, PolicyConfig, PolicyRule
from agentd.profiles import ApexCoderProfile
from agentd.run_graph import fork_run
from agentd.sdk import Agent
from agentd.state import Message, ModelResponse, PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult, ToolStep, Workspace
from agentd.tools import ReadContextTool, ShellTool, default_tools


class RecordingModel:
    name = "recording"

    def __init__(self, responses):
        self.responses = list(responses)
        self.messages = []

    def complete(self, messages, tools, state):
        del tools, state
        self.messages.append(list(messages))
        return self.responses.pop(0)


class AllowAllPolicy:
    def evaluate(self, call, state):
        del call, state
        return PolicyDecision.allow()


def test_toolresult_contextfs_and_context_report_contracts(tmp_path) -> None:
    call = ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"print('x' * 80)\""})
    kernel = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(call,)), ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        budgets=RunBudgets(max_command_output_chars_visible=16),
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
    assert reread.data["output_chars"] >= 80
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
        policy=LocalPolicy(),
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
                ModelResponse(tool_calls=(ToolCall(name="search_repo", args={"query": "test_ok"}),)),
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff --no-index hello.py hello.py"}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -m pytest hello.py"}),)),
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "curl https://example.com"}),)),
                ModelResponse(content="Done. Network command was blocked by policy. Verification passed.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        workspace_mode="current",
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
    search_output = write_text_artifact(state, "search-output-call_search.txt", "generated.txt:1:hello contextfs\n", kind="search_captured_output")
    delta = write_text_artifact(state, "workspace-delta-0001.patch", "diff --git a/generated.txt b/generated.txt\n", kind="workspace_delta")
    state.emit("diff.snapshot", {"tool_call_id": "call_shell", "path": delta, "paths": ["generated.txt"]})
    state.emit("command.completed", {"cmd": f"{sys.executable} -m unittest discover -s .", "ok": True, "returncode": 0})
    state.observations.extend(
        [
            Observation(kind="file_changed", subject="generated.txt", summary="generated.txt changed by shell.", refs=(delta,), data={"source": "workspace_delta"}),
            Observation(kind="verification", subject="unittest", summary="Verification command passed.", data={"cmd": f"{sys.executable} -m unittest discover -s ."}),
            Observation(kind="policy_block", subject="network", summary="Network command was blocked by policy.", data={"capability": "network", "source": "policy"}),
            Observation(kind="sandbox_block", subject="filesystem", summary="Filesystem write was blocked by sandbox.", data={"capability": "filesystem", "source": "sandbox"}),
        ]
    )
    search_call = ToolCall(id="call_search", name="search_repo", args={"query": "hello contextfs"})
    search_result = ToolResult(
        tool_name="search_repo",
        call_id="call_search",
        output="generated.txt:1:hello contextfs",
        artifact_path=search_output,
        data={"output_artifact": search_output, "query": "hello contextfs"},
    )
    state.tool_steps.append(ToolStep(call=search_call, result=search_result))
    state.transcript.record_tool_call(
        item_id="transcript-tool-call-0001",
        turn_id="turn-0001",
        model_call_id="model-call-0001",
        tool_call_id="call_search",
        tool_name="search_repo",
        args={"query": "hello contextfs"},
    )
    state.transcript.record_tool_result(
        item_id="transcript-tool-result-0002",
        turn_id="turn-0001",
        tool_call_id="call_search",
        tool_name="search_repo",
        ok=True,
        summary="generated.txt:1:hello contextfs",
        failure_kind=None,
        artifact_refs=(search_output,),
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
        "context/tools/read_context.md",
        "context/tools/search_repo.md",
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
    assert "artifacts/search-output" in (state.output_dir / "context" / "tools" / "search_repo.md").read_text()

    reader = ReadContextTool()
    for relative in [
        "context/INDEX.md",
        "context/current_diff.patch",
        "context/observations.md",
        "context/transcript.md",
        "context/tools/search_repo.md",
    ]:
        result = reader.run(ToolCall(name="read_context", args={"path": relative}), state)
        assert result.ok is True, result.output


def test_read_context_safely_allows_recovery_artifacts_but_not_raw_model_artifacts(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="search_repo", args={"query": "needle"}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("context reader safety", workspace=tmp_path, run_id="run_context_reader_safety")

    state.output_dir.mkdir(parents=True, exist_ok=True)
    context_report = next(event.data["path"] for event in state.events if event.type == "artifact.created" and event.data["kind"] == "context_report")
    search_output = next(event.data["path"] for event in state.events if event.type == "artifact.created" and event.data["kind"] == "search_captured_output")
    reader = ReadContextTool()

    assert reader.run(ToolCall(name="read_context", args={"path": "context/INDEX.md"}), state).ok is True
    assert reader.run(ToolCall(name="read_context", args={"path": search_output}), state).ok is True
    assert reader.run(ToolCall(name="read_context", args={"path": context_report}), state).ok is False
    assert reader.run(ToolCall(name="read_context", args={"path": "events.jsonl"}), state).ok is False
    assert reader.run(ToolCall(name="read_context", args={"path": "artifacts/model-response-0001.json"}), state).ok is False
    forged_checkpoint = state.output_dir / "artifacts" / "context-checkpoint-9999.md"
    forged_checkpoint.write_text("forged checkpoint\n")
    assert reader.run(ToolCall(name="read_context", args={"path": "artifacts/context-checkpoint-9999.md"}), state).ok is False


def test_contextfs_diff_excludes_custom_output_dir_symlinks_and_large_files(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("outside-secret\n")
    try:
        (tmp_path / "linked-secret.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    (tmp_path / "big.bin").write_bytes(b"x" * 1_000_001)
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
    assert "big.bin" in diff
    assert "Binary files /dev/null and b/big.bin differ" in diff


def test_read_context_blocks_stale_context_files_not_generated_this_run(tmp_path) -> None:
    state = RunState.create("stale context", Workspace(tmp_path), run_id="run_stale_context")
    stale = state.output_dir / "context" / "shell" / "0001-stale.txt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale-secret\n")
    refresh_contextfs(state)

    result = ReadContextTool().run(ToolCall(name="read_context", args={"path": "context/shell/0001-stale.txt"}), state)

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
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"printf 'visible\\n' > created.txt && {sys.executable} -c \"open('big.bin', 'wb').write(b'x' * 1000001)\""}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
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
            subject="artifacts/model-response-0001.json",
            summary="command used TOKEN=secret-value against artifacts/model-response-0001.json",
            refs=("artifacts/model-response-0001.json",),
            data={"cmd": "curl https://example.com?token=secret-value", "artifact": "artifacts/model-response-0001.json"},
        )
    )
    state.transcript.record_tool_call(
        item_id="transcript-tool-call-sanitize",
        turn_id="turn-x",
        model_call_id="model-call-x",
        tool_call_id="call_sanitize",
        tool_name="shell",
        args={"cmd": "curl https://example.com?token=secret-value"},
    )
    refresh_contextfs(state)
    transcript = (state.output_dir / "context" / "transcript.md").read_text()
    observations = (state.output_dir / "context" / "observations.md").read_text()
    assert "secret-value" not in transcript
    assert "secret-value" not in observations
    assert "artifacts/model-response-0001" not in transcript
    assert "artifacts/model-response-0001" not in observations


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
        policy=LocalPolicy(),
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
    checkpoint = ReadContextTool().run(ToolCall(name="read_context", args={"path": artifact}), state)

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
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("avoid repeated failures", workspace=tmp_path, run_id="run_progress_guard_contract")

    assert state.failed is False
    blocked = state.tool_steps[-1].result
    assert blocked.failure_kind == "progress_blocked"
    assert blocked.data["progress_blocked"] is True
    assert any(observation.kind == "policy_block" for observation in state.observations)


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
        policy=LocalPolicy(),
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


def test_initial_model_context_includes_contextfs_index(tmp_path) -> None:
    model = RecordingModel([ModelResponse(content="done", finish_reason="stop")])
    state = Kernel(
        model=model,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("read contextfs first", workspace=tmp_path, run_id="run_initial_contextfs")

    assert state.failed is False
    first_request = model.messages[0]
    contextfs = next(message for message in first_request if message.meta.get("context_layer") == "contextfs_index")
    assert ".tinyagent/runs/run_initial_contextfs/context/task.md" in contextfs.content


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
        policy=LocalPolicy(),
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
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('generated.txt', 'w').write('x')\""}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
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
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('generated.txt', 'w').write('x')\""}),)),
                ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "generated.txt"}),)),
                ModelResponse(content="Done. Could not run verification in this environment.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("read only", workspace=tmp_path, run_id="run_read_only_delta")

    assert state.failed is False
    assert not any(event.type == "workspace.mutation.detected" for event in state.events)


def test_workspace_delta_detects_edit_to_existing_untracked_git_file(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "notes.txt").write_text("before\n")
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('notes.txt', 'w').write('after')\""}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
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
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('new.txt', 'w').write('new after')\""}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("edit a file inside an existing untracked dir", workspace=tmp_path, run_id="run_untracked_dir_delta")

    assert any(event.type == "file.changed" and event.data["path"] == "notes/draft.txt" for event in state.events)


def test_workspace_delta_ignores_common_generated_artifacts(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('.coverage', 'w').write('data')\""}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("write generated test artifact", workspace=tmp_path, run_id="run_generated_artifact_delta")

    assert state.failed is False
    assert not any(event.type == "workspace.mutation.detected" for event in state.events)


def test_failed_shell_mutation_still_requires_mutation_gates(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"open('failed.txt', 'w').write('x'); raise SystemExit(1)\""}),)),
                ModelResponse(content="Command failed.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
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
        policy=LocalPolicy(),
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
    assert hints[1] == 'rg "FAILED|ERROR|Traceback|AssertionError" \'/tmp/tiny agent/context/output file.txt\''


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
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("deny network", workspace=tmp_path, run_id="run_policy_metric_once")

    metrics = extract_run_metrics(state.output_dir)
    assert metrics.policy_denials == 1
    assert metrics.tool_error_count == 1
    assert metrics.tool_error_kinds["policy_denied"] == 1
    assert "unknown" not in metrics.tool_error_kinds


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
        policy=LocalPolicy(),
        workspace_mode="current",
        budgets=RunBudgets(max_turns=3),
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


def test_deprecated_worktree_sandbox_alias_maps_to_workspace_mode(tmp_path) -> None:
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

    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        sandbox_mode="worktree",
    ).run("use worktree alias", workspace=tmp_path, run_id="run_worktree_sandbox")

    assert state.workspace.root != tmp_path.resolve()
    assert state.output_dir == tmp_path.resolve() / ".tinyagent" / "runs" / "run_worktree_sandbox"
    boundary = next(event for event in state.events if event.type == "workspace.boundary")
    assert boundary.data["mode"] == "worktree"
    assert boundary.data["effective_mode"] == "worktree"
    assert boundary.data["sandbox_mode"] == "none"
    assert boundary.data["sandbox_backend"] == "none"
    assert boundary.data["sandbox_alias"] == "worktree"
    assert boundary.data["sandbox_enforced"] is False


def test_container_sandbox_mode_fails_setup_until_backend_exists(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentd.workspace.detect_container_backend", lambda: None)
    kernel = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        sandbox_mode="container",
    )

    with pytest.raises(ValueError, match="requires a usable Docker or Podman backend"):
        kernel.run("use container sandbox", workspace=tmp_path, run_id="run_container_sandbox")


def test_container_sandbox_mode_records_enforced_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agentd.workspace.detect_container_backend", lambda: "docker")
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
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


def test_shell_container_sandbox_wraps_process_with_isolated_home_and_network(tmp_path) -> None:
    from agentd.tools.builtins.shell import _popen_command

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


def test_shell_container_timeout_kills_cidfile_container(tmp_path, monkeypatch) -> None:
    from agentd.tools.builtins.shell import _ProcessLaunch, _terminate_container

    cidfile = tmp_path / "container.cid"
    cidfile.write_text("abc123\n")
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("agentd.tools.builtins.shell.subprocess.run", fake_run)

    _terminate_container(_ProcessLaunch(args=["docker"], shell=False, container_backend="docker", cidfile=cidfile))

    assert calls == [["docker", "kill", "abc123"], ["docker", "rm", "-f", "abc123"]]


def test_container_image_rejects_option_like_values(monkeypatch) -> None:
    from agentd.container_sandbox import default_container_image

    monkeypatch.setenv("TINYAGENT_CONTAINER_IMAGE", "--privileged")

    with pytest.raises(ValueError, match="cannot start with"):
        default_container_image()


def test_policy_and_sandbox_denials_have_distinct_failure_dimensions(tmp_path) -> None:
    network_call = ToolCall(name="shell", args={"cmd": "curl https://example.com"})
    policy_state = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(network_call,)), ModelResponse(content="blocked", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        workspace_mode="current",
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
        model=FakeModelProvider([ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "printf x"}),)), ModelResponse(content="blocked", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=AllowAllPolicy(),
        hooks=[SandboxBlockingHook()],
        workspace_mode="current",
    ).run("synthetic sandbox block", workspace=tmp_path, run_id="run_sandbox_dimensions")

    sandbox_result = sandbox_state.tool_results[0]
    assert sandbox_result.failure_kind == "sandbox_blocked"
    assert sandbox_result.data["source"] == "sandbox"
    assert any(observation.kind == "sandbox_block" and observation.data["source"] == "sandbox" for observation in sandbox_state.observations)


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
        policy=LocalPolicy(),
        approval_mode="yolo",
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
        policy=LocalPolicy(),
        workspace_mode="current",
    ).run("final contextfs", workspace=tmp_path, run_id="run_final_contextfs")

    raw = (state.output_dir / "context" / "history" / "raw.jsonl").read_text()
    assert '"type": "run.completed"' in raw


def test_hook_can_inject_context_and_block_tool(tmp_path) -> None:
    class BlockingHook:
        name = "blocking-hook"

        def on_context(self, state: RunState, context: BuiltContext) -> BuiltContext:
            return replace(context, messages=[*context.messages, Message(role="user", content="hook context")])

        def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolResult:
            return ToolResult(tool_name=call.name, call_id=call.id, output="hook blocked", ok=False, failure_kind="policy_denied")

    call = ToolCall(name="shell", args={"cmd": "printf should-not-run"})
    state = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(call,)), ModelResponse(content="blocked by hook", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=[ShellTool()],
        policy=LocalPolicy(),
        hooks=[BlockingHook()],
        workspace_mode="current",
    ).run("hook test", workspace=tmp_path, run_id="run_hook_contract")

    assert state.failed is False
    assert "command.started" not in [event.type for event in state.events]
    assert any(event.type == "hook.completed" and event.data["method"] == "on_context" for event in state.events)
    assert any(event.type == "tool.execution.blocked" for event in state.events)
    first_context = next(event for event in state.events if event.type == "model.call.started")
    assert "hook context" in (state.output_dir / first_context.data["context_artifact"]).read_text()


def test_hook_mutated_tool_call_is_rechecked_by_policy(tmp_path) -> None:
    class MutatingHook:
        name = "mutating-hook"

        def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolCall:
            assert decision.allowed is True
            return ToolCall(name="shell", args={"cmd": "curl https://example.com"}, id=call.id)

    call = ToolCall(name="shell", args={"cmd": "git diff -- README.md"})
    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(call,)),
                ModelResponse(content="Network command was denied by policy.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        hooks=[MutatingHook()],
        workspace_mode="current",
    ).run("mutate tool", workspace=tmp_path, run_id="run_hook_policy_recheck")

    assert state.failed is False
    assert "command.started" not in [event.type for event in state.events]
    decisions = [event for event in state.events if event.type == "policy.evaluated"]
    assert [decision.data["kind"] for decision in decisions] == ["allow", "deny"]
    assert decisions[-1].data["permission"] == "network"


def test_hook_failure_fails_closed_by_default(tmp_path) -> None:
    class FailingHook:
        name = "failing-hook"

        def before_model_call(self, state: RunState, messages, tools):
            raise RuntimeError("mandatory hook failed")

    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="should not run", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
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
            policy=LocalPolicy(),
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
        policy=LocalPolicy(),
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
