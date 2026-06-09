from __future__ import annotations

import json
import os
import sys

import pytest

from tinyagent.core.kernel import Kernel
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import LocalPolicy, PolicyDecision
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.state import ApprovalRequest, ModelResponse, RunState, ToolCall, Workspace
from tinyagent.core.tools import default_tools
from tinyagent.extensions.workspace_snapshot import (
    WorkspaceSnapshotExtension,
    create_workspace_snapshot,
    restore_workspace_snapshot,
)

_VERIFY_NOTE_AFTER = f"{sys.executable} -c \"from pathlib import Path; assert Path('note.txt').read_text() == 'after\\\\n'\""


class WorkspaceShellPolicy(LocalPolicy):
    def _evaluate_shell(self, call: ToolCall, state: RunState) -> PolicyDecision:
        decision = super()._evaluate_shell(call, state)
        if decision.kind == "needs_approval" and decision.permission == "bash":
            return PolicyDecision.allow("test permits workspace shell", matched_rule="test.bash.allow", permission="bash")
        return decision


def test_workspace_snapshot_restore_rewinds_files(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("before\n")

    snapshot = create_workspace_snapshot(
        tmp_path,
        tmp_path / ".tinyagent" / "snapshots" / "s1",
        ["note.txt", "created.txt"],
        label="test",
    )
    (tmp_path / "note.txt").write_text("after\n")
    (tmp_path / "created.txt").write_text("new\n")

    restored = restore_workspace_snapshot(tmp_path, snapshot.manifest_path)

    assert restored.restored == ("note.txt",)
    assert restored.deleted == ("created.txt",)
    assert (tmp_path / "note.txt").read_text() == "before\n"
    assert not (tmp_path / "created.txt").exists()
    manifest = json.loads(snapshot.manifest_path.read_text())
    assert manifest["schema"] == "tinyagent.workspace_snapshot.v1"
    assert manifest["paths"] == ["note.txt", "created.txt"]


def test_workspace_snapshot_rejects_protected_or_symlink_paths(tmp_path) -> None:
    (tmp_path / ".env").write_text("TOKEN=secret\n")
    with pytest.raises(ValueError, match="protected"):
        create_workspace_snapshot(tmp_path, tmp_path / "snapshot-secret", [".env"])

    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("outside\n")
    os.symlink(outside, tmp_path / "link.txt")
    with pytest.raises(ValueError, match="symlink"):
        create_workspace_snapshot(tmp_path, tmp_path / "snapshot-symlink", ["link.txt"])


def test_workspace_snapshot_rejects_symlinked_storage_and_tampered_hash(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("before\n")
    outside_dir = tmp_path.parent / f"{tmp_path.name}-storage-outside"
    outside_dir.mkdir()
    snapshot_link = tmp_path / "snapshot-link"
    os.symlink(outside_dir, snapshot_link)
    with pytest.raises(ValueError, match="root crosses a symlink"):
        create_workspace_snapshot(tmp_path, snapshot_link, ["note.txt"])

    snapshot_root = tmp_path / "snapshot-storage"
    snapshot_root.mkdir()
    os.symlink(outside_dir, snapshot_root / "files")

    with pytest.raises(ValueError, match="storage path crosses a symlink"):
        create_workspace_snapshot(tmp_path, snapshot_root, ["note.txt"])

    snapshot = create_workspace_snapshot(tmp_path, tmp_path / "snapshot-good", ["note.txt"])
    manifest = json.loads(snapshot.manifest_path.read_text())
    manifest["files"][0]["sha256"] = ""
    snapshot.manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="missing sha256"):
        restore_workspace_snapshot(tmp_path, snapshot.manifest_path)


def test_workspace_snapshot_hook_snapshots_needs_approval_decisions(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("before\n")
    state = RunState.create("snapshot approval", Workspace(tmp_path), run_id="run_snapshot_needs_approval")
    hook = WorkspaceSnapshotExtension().hooks()[0]
    call = ToolCall(name="write_file", args={"path": "note.txt", "content": "after\n"})
    approval = ApprovalRequest(
        approval_id="approval_snapshot",
        run_id=state.run_id,
        turn_id=None,
        step_id=None,
        action_kind="patch",
        tool_name="write_file",
        cwd=str(tmp_path),
        args_preview="write_file note.txt",
        command=None,
        risk="medium",
    )

    result = hook.before_tool_call(state, call, PolicyDecision.needs_approval("dirty workspace", approval))

    assert result is None
    assert any(event.type == "extension.event" and event.data.get("event") == "workspace.snapshot.created" for event in state.events)


def test_workspace_snapshot_extension_records_before_edit_artifact(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("before\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: note.txt",
            "@@",
            "-before",
            "+after",
            "*** End Patch",
        ]
    )

    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(id="call_patch", name="apply_patch", args={"patch": patch}),)),
                ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "note.txt"}),)),
                ModelResponse(
                    tool_calls=(
                        ToolCall(
                            name="shell",
                            args={"cmd": _VERIFY_NOTE_AFTER},
                        ),
                    )
                ),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=WorkspaceShellPolicy(),
        extensions=[WorkspaceSnapshotExtension()],
        workspace_mode="current",
    ).run("edit with snapshot", workspace=tmp_path, run_id="run_snapshot_extension")

    assert state.failed is False
    snapshot_event = next(
        event
        for event in state.events
        if event.type == "extension.event" and event.data.get("event") == "workspace.snapshot.created"
    )
    assert snapshot_event.data["paths"] == ["note.txt"]
    assert snapshot_event.artifact_refs == [snapshot_event.data["manifest"]]
    manifest_path = state.output_dir / snapshot_event.data["manifest"]
    manifest = json.loads(manifest_path.read_text())
    assert manifest["label"] == "before-apply_patch"
    assert manifest["files"][0]["path"] == "note.txt"

    restore_workspace_snapshot(tmp_path, manifest_path)

    assert (tmp_path / "note.txt").read_text() == "before\n"


def test_workspace_snapshot_extension_blocks_current_run_artifact_paths(tmp_path) -> None:
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: out/events.jsonl",
            "+tamper",
            "*** End Patch",
        ]
    )

    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(id="call_patch", name="apply_patch", args={"patch": patch}),)),
                ModelResponse(content="Snapshot failed, so the edit was blocked and verification cannot run.", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=WorkspaceShellPolicy(),
        extensions=[WorkspaceSnapshotExtension()],
        workspace_mode="current",
    ).run("edit run artifact", workspace=tmp_path, run_id="run_snapshot_output_path", output_dir=tmp_path / "out")

    assert state.failed is False
    assert state.tool_results[0].failure_kind == "snapshot_failed"
    assert "inside current run artifacts" in state.tool_results[0].output
    assert not any(event.type == "extension.event" and event.data.get("event") == "workspace.snapshot.created" for event in state.events)


def test_workspace_snapshot_extension_is_not_enabled_by_default(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("before\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: note.txt",
            "@@",
            "-before",
            "+after",
            "*** End Patch",
        ]
    )

    state = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(id="call_patch", name="apply_patch", args={"patch": patch}),)),
                ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "note.txt"}),)),
                ModelResponse(
                    tool_calls=(
                        ToolCall(
                            name="shell",
                            args={"cmd": _VERIFY_NOTE_AFTER},
                        ),
                    )
                ),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=WorkspaceShellPolicy(),
        workspace_mode="current",
    ).run("edit without snapshot", workspace=tmp_path, run_id="run_no_snapshot_extension")

    assert state.failed is False
    snapshot_events = [
        event for event in state.events if event.type == "extension.event" and event.data.get("event", "").startswith("workspace.snapshot.")
    ]
    assert snapshot_events == []
