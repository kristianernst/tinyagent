from __future__ import annotations

import json

import pytest

from tinyagent.core.context_sources import ContextReadTool, ContextSearchTool
from tinyagent.core.contextfs import _write_text, allowed_context_read_paths, refresh_contextfs, write_context_tool_output
from tinyagent.core.contextfs_render import OPTIONAL_CONTEXT_FILE_RELS, STATIC_CONTEXT_FILE_RELS
from tinyagent.core.observations import Observation
from tinyagent.core.output import write_text_artifact
from tinyagent.core.state import RunBudgets, RunState, ToolCall, ToolResult, ToolStep, Workspace


def test_contextfs_render_plan_snapshots_generated_recovery_surface(tmp_path) -> None:
    state = _snapshot_state(tmp_path)

    refresh_contextfs(state)

    files = sorted(path.relative_to(state.output_dir).as_posix() for path in (state.output_dir / "context").rglob("*") if path.is_file())
    assert files == [
        "context/INDEX.md",
        "context/current_diff.md",
        "context/current_diff.patch",
        "context/current_status.md",
        "context/diffs/0001-workspace-delta-0001.patch",
        "context/diffs/INDEX.md",
        "context/environment.md",
        "context/history/compacted.md",
        "context/history/raw.jsonl",
        "context/history/summary.md",
        "context/last_failure.md",
        "context/memory/todo.md",
        "context/observations.md",
        "context/shell/0001-call_ok.txt",
        "context/shell/0002-call_fail.txt",
        "context/task.md",
        "context/tools/INDEX.md",
        "context/tools/apply_patch.md",
        "context/tools/context_read.md",
        "context/tools/context_search.md",
        "context/tools/read_file.md",
        "context/tools/search_code.md",
        "context/tools/shell.md",
        "context/tools/str_replace_edit.md",
        "context/tools/write_file.md",
        "context/transcript.md",
    ]
    assert (state.output_dir / "context/task.md").read_text() == "\n".join(
        [
            "# Task",
            "",
            "snapshot contextfs render",
            "",
            "run_id: run_contextfs_render_snapshot",
            "status: new",
            "turn_count: 0",
            "tool_call_count: 0",
            "",
        ]
    )
    index = (state.output_dir / "context/INDEX.md").read_text()
    assert "- context/current_status.md: latest git status and diff stat." in index
    assert "- context/current_diff.patch: latest git diff patch." in index
    assert "- context/environment.md: cwd, shell, workspace, approvals, and sandbox metadata." in index
    assert "- context/memory/todo.md: run-scoped working todo state." in index
    assert 'context_read({"ref":"contextfs:context/shell/0002-call_fail.txt"})' in index
    assert state.output_dir.as_posix() not in index

    assert (state.output_dir / "context/last_failure.md").read_text() == "\n".join(
        [
            "# Last Failure",
            "",
            "tool: shell",
            "call_id: call_fail",
            "failure_kind: command_failed",
            "artifact: context/shell/0002-call_fail.txt",
            "",
            "## Preview",
            "",
            "```text",
            "failed output",
            "```",
            "",
        ]
    )
    observations = (state.output_dir / "context/observations.md").read_text()
    assert "## file_changed: generated.txt" in observations
    assert "refs: artifacts/workspace-delta-0001.patch" in observations
    assert 'data: `{"cmd": "(redacted)"}`' in observations
    transcript = (state.output_dir / "context/transcript.md").read_text()
    assert "## tool_call: transcript-call-0001" in transcript
    assert 'data: `{"args": "(redacted)"}`' in transcript
    assert "refs: context/shell/0002-call_fail.txt" in transcript
    assert (state.output_dir / "context/tools/INDEX.md").read_text().startswith("# Tool Context\n\n- context/tools/read_file.md")
    assert (state.output_dir / "context/diffs/INDEX.md").read_text() == "\n".join(
        [
            "# ContextFS Diffs",
            "",
            "- context/current_diff.patch: latest aggregate workspace diff.",
            "- context/diffs/0001-workspace-delta-0001.patch: copied from `artifacts/workspace-delta-0001.patch`.",
            "",
        ]
    )


def test_contextfs_specs_are_allowed_without_clobbering_external_todo(tmp_path) -> None:
    state = RunState.create("todo ownership", Workspace(tmp_path), run_id="run_contextfs_todo")
    todo_path = state.output_dir / "context/memory/todo.md"
    todo_path.parent.mkdir(parents=True, exist_ok=True)
    todo_path.write_text("# Working Todo\n\n- [ ] keep me\n")

    refresh_contextfs(state)

    assert todo_path.read_text() == "# Working Todo\n\n- [ ] keep me\n"
    allowed = allowed_context_read_paths(state)
    assert set(STATIC_CONTEXT_FILE_RELS) <= allowed
    assert set(OPTIONAL_CONTEXT_FILE_RELS) <= allowed


def test_contextfs_render_plan_keeps_search_and_read_edges(tmp_path) -> None:
    state = RunState.create("large read edge", Workspace(tmp_path), run_id="run_contextfs_large_edge")
    refresh_contextfs(state)
    (state.output_dir / "context/last_failure.md").write_text("needle\n" * 600_000)

    searched = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "task", "source": "contextfs"}), state)
    large_stub = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "last_failure", "source": "contextfs"}), state)
    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "contextfs:context/last_failure.md"}), state)

    assert searched.ok is True
    assert "contextfs:context/task.md" in searched.output
    assert large_stub.ok is True
    assert "File is too large for context_search." in large_stub.output
    assert read.ok is False
    assert "too large" in read.output


def test_contextfs_exposes_truncated_context_tool_output_artifacts(tmp_path) -> None:
    state = RunState.create(
        "truncated dynamic context",
        Workspace(tmp_path),
        run_id="run_contextfs_truncated_context_tools",
        budgets=RunBudgets(max_tool_output_tokens_visible=20),
    )
    refresh_contextfs(state)
    search = ContextSearchTool().run(
        ToolCall(id="call_search", name="context_search", args={"query": "truncated", "source": "contextfs"}), state
    )
    state.tool_steps.append(ToolStep(ToolCall(id="call_search", name="context_search", args={"query": "truncated"}), search))

    read = ContextReadTool().run(
        ToolCall(
            id="call_read",
            name="context_read",
            args={"ref": "contextfs:artifacts/context-search-call_search.txt", "max_lines": 1000},
        ),
        state,
    )
    state.tool_steps.append(
        ToolStep(
            ToolCall(id="call_read", name="context_read", args={"ref": "contextfs:artifacts/context-search-call_search.txt"}),
            read,
        )
    )
    refresh_contextfs(state)

    assert search.truncated is True
    assert search.artifact_path == "artifacts/context-search-call_search.txt"
    assert read.truncated is True
    assert read.artifact_path == "artifacts/context-read-call_read.txt"
    index = (state.output_dir / "context/INDEX.md").read_text()
    assert "artifacts/context-search-call_search.txt: context_search `call_search` ok" in index
    assert "artifacts/context-read-call_read.txt: context_read `call_read` ok" in index
    assert "artifacts/context-search-call_search.txt" in (state.output_dir / "context/tools/context_search.md").read_text()
    assert "artifacts/context-read-call_read.txt" in (state.output_dir / "context/tools/context_read.md").read_text()
    assert (
        ContextReadTool()
        .run(
            ToolCall(name="context_read", args={"ref": "contextfs:artifacts/context-read-call_read.txt", "max_lines": 5}),
            state,
        )
        .ok
        is True
    )


def test_contextfs_tool_output_sanitizes_reserved_path_components(tmp_path) -> None:
    state = RunState.create("reserved path output", Workspace(tmp_path), run_id="run_reserved_context_path")

    path = write_context_tool_output(state, ToolCall(id="..", name="..", args={}), "output\n", kind="tool_output")

    assert path == "context/call/0001-call.txt"
    assert (state.output_dir / "context" / "call" / "0001-call.txt").read_text() == "output\n"
    assert not (state.output_dir / "0001-call.txt").exists()


def test_contextfs_render_write_stays_inside_context_dir(tmp_path) -> None:
    state = RunState.create("contextfs write boundary", Workspace(tmp_path), run_id="run_contextfs_write_boundary")
    outside = tmp_path / "outside.md"

    for relative in ("../outside.md", "context/../outside.md", str(outside), ""):
        with pytest.raises(ValueError):
            _write_text(state, relative, "escape\n")

    assert not outside.exists()
    assert not (state.output_dir / "outside.md").exists()


def test_contextfs_render_uses_captured_output_artifact(tmp_path) -> None:
    state = RunState.create("captured artifact render", Workspace(tmp_path), run_id="run_contextfs_captured_artifact")
    context_artifact = write_context_tool_output(
        state, ToolCall(id="call_capture", name="shell", args={}), "tool output\n", kind="shell_output"
    )
    captured = write_text_artifact(state, "workspace-delta-0001.patch", "diff --git a/file.txt b/file.txt\n", kind="workspace_delta")
    state.tool_steps.append(
        ToolStep(
            call=ToolCall(id="call_capture", name="shell", args={"cmd": "pytest"}),
            result=ToolResult(
                tool_name="shell",
                call_id="call_capture",
                output="failed",
                ok=False,
                artifact_path=context_artifact,
                data={"context_artifact": context_artifact, "captured_output_artifact": captured},
                failure_kind="command_failed",
            ),
        )
    )

    refresh_contextfs(state)

    last_failure = (state.output_dir / "context/last_failure.md").read_text()
    tool_doc = (state.output_dir / "context/tools/shell.md").read_text()
    index = (state.output_dir / "context/INDEX.md").read_text()
    for artifact in (context_artifact, captured):
        assert artifact in last_failure
        assert artifact in tool_doc
        assert artifact in index


def _snapshot_state(tmp_path) -> RunState:
    state = RunState.create("snapshot contextfs render", Workspace(tmp_path), run_id="run_contextfs_render_snapshot")
    state.output_dir.mkdir(parents=True, exist_ok=True)
    _write_context_artifact(state, "context/shell/0001-call_ok.txt", "ok output\n", tool_call_id="call_ok")
    _write_context_artifact(state, "context/shell/0002-call_fail.txt", "failed output\n", tool_call_id="call_fail")
    ok_call = ToolCall(id="call_ok", name="shell", args={"cmd": "printf ok"})
    fail_call = ToolCall(id="call_fail", name="shell", args={"cmd": "pytest"})
    state.tool_steps.extend(
        [
            ToolStep(
                call=ok_call,
                result=ToolResult(
                    tool_name="shell",
                    call_id="call_ok",
                    output="ok output",
                    artifact_path="context/shell/0001-call_ok.txt",
                ),
            ),
            ToolStep(
                call=fail_call,
                result=ToolResult(
                    tool_name="shell",
                    call_id="call_fail",
                    output="failed output",
                    ok=False,
                    content_preview="failed output",
                    artifact_path="context/shell/0002-call_fail.txt",
                    failure_kind="command_failed",
                    data={"failure_kind": "command_failed"},
                ),
            ),
        ]
    )
    delta = write_text_artifact(state, "workspace-delta-0001.patch", "diff --git a/generated.txt b/generated.txt\n", kind="workspace_delta")
    checkpoint = write_text_artifact(state, "context-checkpoint-0001.md", "checkpoint token=secret\n", kind="context_checkpoint")
    state.emit("diff.snapshot", {"tool_call_id": "call_fail", "path": delta, "paths": ["generated.txt"]})
    state.context_checkpoint = f"Checkpoint includes token=secret and {state.output_dir}/hidden"
    state.context_checkpoint_artifact = checkpoint
    state.observations.append(
        Observation(
            kind="file_changed",
            subject="generated.txt",
            summary="generated.txt changed by shell.",
            refs=(delta,),
            data={"cmd": "pytest --token=secret"},
        )
    )
    state.transcript.record_tool_call(
        item_id="transcript-call-0001",
        turn_id="turn-0001",
        model_call_id="model-call-0001",
        tool_call_id="call_fail",
        tool_name="shell",
        args={"cmd": "pytest --token=secret"},
    )
    state.transcript.record_tool_result(
        item_id="transcript-result-0002",
        turn_id="turn-0001",
        tool_call_id="call_fail",
        tool_name="shell",
        ok=False,
        summary="failed output",
        failure_kind="command_failed",
        artifact_refs=("context/shell/0002-call_fail.txt",),
    )
    (state.output_dir / "events.jsonl").write_text(
        json.dumps(
            {
                "seq": 1,
                "type": "command.completed",
                "time": "2026-05-03T00:00:00Z",
                "visibility": "debug",
                "data": {"cmd": "pytest --token=raw-history-secret", "output_preview": "raw-history-secret"},
                "artifact_refs": ["artifacts/model-response-0001.json", delta],
            },
            sort_keys=True,
        )
        + "\n"
    )
    todo = state.output_dir / "context/memory/todo.md"
    todo.parent.mkdir(parents=True, exist_ok=True)
    todo.write_text("# Working Todo\n\n- [ ] preserve external todo\n")
    return state


def _write_context_artifact(state: RunState, rel: str, content: str, *, tool_call_id: str) -> None:
    path = state.output_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    state.emit(
        "contextfs.artifact.written",
        {
            "path": rel,
            "kind": "tool_output",
            "tool_call_id": tool_call_id,
            "tool": "shell",
            "bytes": len(content.encode()),
        },
    )
