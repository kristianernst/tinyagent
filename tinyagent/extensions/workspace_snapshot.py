"""Opt-in workspace snapshot and rewind extension."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tinyagent.core.contracts import Tool
from tinyagent.core.events import json_safe
from tinyagent.core.extensions import ExtensionInfo
from tinyagent.core.path_safety import checked_relative_path, looks_like_secret_path, resolved_relative_to, safe_artifact_name
from tinyagent.core.skills import SkillSource
from tinyagent.core.state import PolicyDecision, RunState, ToolCall, ToolResult
from tinyagent.core.tools import patch_paths

SNAPSHOT_SCHEMA = "tinyagent.workspace_snapshot.v1"
_PROTECTED_NAMES = frozenset({".tinyagent"})


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_dir: Path
    manifest_path: Path
    manifest: dict[str, object]
    paths: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "snapshot_dir": str(self.snapshot_dir),
            "manifest_path": str(self.manifest_path),
            "paths": list(self.paths),
        }


@dataclass(frozen=True)
class RestoreResult:
    manifest_path: Path
    restored: tuple[str, ...]
    deleted: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "manifest_path": str(self.manifest_path),
            "restored": list(self.restored),
            "deleted": list(self.deleted),
        }


class WorkspaceSnapshotExtension:
    """Snapshots edit targets before file-edit tools run.

    The extension is deliberately not part of the default profile. Add it to a
    Kernel with `extensions=[WorkspaceSnapshotExtension()]` when rewind evidence
    is wanted for a run.
    """

    name = "workspace-snapshot"

    def __init__(self, *, max_paths: int = 64) -> None:
        self._hook = _WorkspaceSnapshotHook(max_paths=max_paths)

    def info(self) -> ExtensionInfo:
        return ExtensionInfo(
            name=self.name,
            description="Creates before-edit workspace snapshots with manifest artifacts.",
            permissions=("filesystem",),
        )

    def hooks(self) -> Sequence[_WorkspaceSnapshotHook]:
        return (self._hook,)

    def tools(self) -> Sequence[Tool]:
        return ()

    def skills(self) -> Sequence[SkillSource]:
        return ()

    def context_sources(self) -> Sequence[object]:
        return ()


class _WorkspaceSnapshotHook:
    name = "workspace-snapshot"

    def __init__(self, *, max_paths: int) -> None:
        self.max_paths = max_paths

    def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolCall | ToolResult | None:
        if decision.kind == "deny":
            return None
        paths = _tool_paths(call)
        if not paths:
            return None
        if len(paths) > self.max_paths:
            return _block_for_snapshot_failure(state, call, f"too many paths for workspace snapshot: {len(paths)} > {self.max_paths}")
        try:
            protected_output = _protected_run_output_path(state, paths)
        except ValueError as exc:
            return _block_for_snapshot_failure(state, call, str(exc))
        if protected_output:
            return _block_for_snapshot_failure(state, call, f"snapshot path is inside current run artifacts: {protected_output}")

        snapshot_id = f"{state.tool_call_count:04d}-{safe_artifact_name(call.id)}-{uuid4().hex[:8]}"
        snapshot_dir = state.output_dir / "artifacts" / "workspace-snapshots" / snapshot_id
        try:
            snapshot = create_workspace_snapshot(
                state.workspace.root,
                snapshot_dir,
                paths,
                label=f"before-{call.name}",
            )
        except (OSError, ValueError) as exc:
            return _block_for_snapshot_failure(state, call, str(exc))

        manifest_ref = snapshot.manifest_path.resolve().relative_to(state.output_dir.resolve()).as_posix()
        state.emit(
            "artifact.created",
            {
                "kind": "workspace_snapshot",
                "path": manifest_ref,
                "bytes": snapshot.manifest_path.stat().st_size,
            },
        )
        state.emit(
            "extension.event",
            {
                "extension": WorkspaceSnapshotExtension.name,
                "event": "workspace.snapshot.created",
                "snapshot_id": snapshot_id,
                "tool_call_id": call.id,
                "tool": call.name,
                "manifest": manifest_ref,
                "paths": list(snapshot.paths),
            },
            artifact_refs=[manifest_ref],
        )
        return None


def create_workspace_snapshot(
    workspace: str | Path,
    snapshot_root: str | Path,
    paths: Iterable[str | Path],
    *,
    label: str = "snapshot",
) -> SnapshotResult:
    root = _workspace_root(workspace)
    relative_paths = _normalise_paths(paths)
    if not relative_paths:
        raise ValueError("Snapshot requires at least one path")

    snapshot_dir = _snapshot_root(snapshot_root)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = _snapshot_storage_target(snapshot_dir, Path("manifest.json"))
    if manifest_path.exists():
        raise ValueError(f"Snapshot manifest already exists: {manifest_path}")
    files_dir = _snapshot_storage_target(snapshot_dir, Path("files"))
    files_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, object]] = []
    for rel in relative_paths:
        target = _workspace_target(root, rel)
        rel_text = rel.as_posix()
        if not target.exists():
            entries.append({"path": rel_text, "existed": False, "bytes": 0, "sha256": "", "snapshot_path": ""})
            continue
        if target.is_dir():
            raise ValueError(f"Workspace snapshot only supports files, not directories: {rel_text}")
        if not target.is_file():
            raise ValueError(f"Workspace snapshot target is not a file: {rel_text}")

        destination = _snapshot_storage_target(snapshot_dir, Path("files") / rel)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = _snapshot_storage_target(snapshot_dir, Path("files") / rel)
        shutil.copy2(target, destination)
        digest = _file_digest(destination)
        entries.append(
            {
                "path": rel_text,
                "existed": True,
                "bytes": destination.stat().st_size,
                "sha256": digest,
                "snapshot_path": destination.relative_to(snapshot_dir).as_posix(),
            }
        )

    manifest: dict[str, object] = {
        "schema": SNAPSHOT_SCHEMA,
        "version": 1,
        "created_at": _utc_timestamp(),
        "label": label,
        "workspace": str(root),
        "paths": [entry["path"] for entry in entries],
        "files": entries,
    }
    manifest_path.write_text(json.dumps(json_safe(manifest), indent=2, sort_keys=True) + "\n")
    return SnapshotResult(
        snapshot_dir=snapshot_dir,
        manifest_path=manifest_path,
        manifest=manifest,
        paths=tuple(str(entry["path"]) for entry in entries),
    )


def restore_workspace_snapshot(workspace: str | Path, manifest_path: str | Path) -> RestoreResult:
    root = _workspace_root(workspace)
    resolved_manifest = Path(manifest_path).expanduser().resolve()
    manifest = json.loads(resolved_manifest.read_text())
    _validate_manifest(manifest, root)

    snapshot_dir = resolved_manifest.parent
    restored: list[str] = []
    deleted: list[str] = []
    for entry in _manifest_entries(manifest):
        rel = _checked_snapshot_path(entry["path"])
        target = _workspace_target(root, rel)
        if entry["existed"]:
            source_rel = checked_relative_path(str(entry["snapshot_path"]), label="Snapshot file path")
            source = (snapshot_dir / source_rel).resolve()
            _require_relative_to(source, snapshot_dir, label="Snapshot file path")
            if not source.is_file():
                raise ValueError(f"Snapshot file is missing: {source_rel.as_posix()}")
            expected_digest = str(entry["sha256"])
            if _file_digest(source) != expected_digest:
                raise ValueError(f"Snapshot file digest mismatch: {source_rel.as_posix()}")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            restored.append(rel.as_posix())
        elif target.exists():
            if target.is_dir():
                raise ValueError(f"Refusing to delete directory during snapshot restore: {rel.as_posix()}")
            target.unlink()
            deleted.append(rel.as_posix())
    return RestoreResult(manifest_path=resolved_manifest, restored=tuple(restored), deleted=tuple(deleted))


def _tool_paths(call: ToolCall) -> tuple[str, ...]:
    if call.name == "apply_patch":
        return tuple(patch_paths(str(call.args.get("patch") or "")))
    if call.name in {"str_replace_edit", "write_file"}:
        path = call.args.get("path")
        return (str(path),) if path else ()
    return ()


def _emit_snapshot_skip(state: RunState, call: ToolCall, reason: str) -> None:
    state.emit(
        "extension.event",
        {
            "extension": WorkspaceSnapshotExtension.name,
            "event": "workspace.snapshot.skipped",
            "tool_call_id": call.id,
            "tool": call.name,
            "reason": reason,
        },
    )


def _block_for_snapshot_failure(state: RunState, call: ToolCall, reason: str) -> ToolResult:
    _emit_snapshot_skip(state, call, reason)
    output = f"workspace snapshot failed before {call.name}: {reason}"
    return ToolResult(
        tool_name=call.name,
        call_id=call.id,
        output=output,
        ok=False,
        data={"blocked": True, "snapshot_failed": True, "failure_kind": "snapshot_failed"},
        failure_kind="snapshot_failed",
        summary=output,
        content_preview=output,
    )


def _protected_run_output_path(state: RunState, paths: Iterable[str]) -> str:
    if resolved_relative_to(state.output_dir, state.workspace.root) is None:
        return ""
    output_dir = state.output_dir.resolve()
    for path in paths:
        rel = checked_relative_path(path, label="Snapshot path")
        target = (state.workspace.root / rel).resolve()
        if resolved_relative_to(target, output_dir) is not None:
            return rel.as_posix()
    return ""


def _workspace_root(workspace: str | Path) -> Path:
    root = Path(workspace).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Workspace does not exist or is not a directory: {root}")
    return root


def _snapshot_root(snapshot_root: str | Path) -> Path:
    raw = Path(snapshot_root).expanduser()
    absolute = raw if raw.is_absolute() else Path.cwd() / raw
    if _path_has_existing_symlink(absolute):
        raise ValueError(f"Snapshot root crosses a symlink: {raw}")
    return absolute.resolve()


def _normalise_paths(paths: Iterable[str | Path]) -> tuple[Path, ...]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        rel = _checked_snapshot_path(path)
        rel_text = rel.as_posix()
        if rel_text in seen:
            continue
        seen.add(rel_text)
        result.append(rel)
    return tuple(result)


def _checked_snapshot_path(path: str | Path) -> Path:
    rel = checked_relative_path(path, label="Snapshot path")
    if looks_like_secret_path(rel) or any(part in _PROTECTED_NAMES for part in rel.parts):
        raise ValueError(f"Snapshot path is protected: {rel.as_posix()}")
    return rel


def _workspace_target(root: Path, rel: Path) -> Path:
    target = root / rel
    if _has_symlink_component(root, rel):
        raise ValueError(f"Snapshot path crosses a symlink: {rel.as_posix()}")
    return target


def _snapshot_storage_target(root: Path, rel: Path) -> Path:
    target = root / rel
    if _has_symlink_component(root, rel):
        raise ValueError(f"Snapshot storage path crosses a symlink: {rel.as_posix()}")
    return target


def _has_symlink_component(root: Path, rel: Path) -> bool:
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _path_has_existing_symlink(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path()
    parts = path.parts[1:] if path.is_absolute() else path.parts
    for part in parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _validate_manifest(manifest: object, workspace: Path) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("Snapshot manifest must be a JSON object")
    if manifest.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("Unsupported snapshot manifest schema")
    manifest_workspace = manifest.get("workspace")
    if manifest_workspace and Path(str(manifest_workspace)).expanduser().resolve() != workspace:
        raise ValueError(f"Snapshot manifest belongs to a different workspace: {manifest_workspace}")


def _manifest_entries(manifest: dict[str, object]) -> list[dict[str, object]]:
    files = manifest.get("files")
    if not isinstance(files, list):
        raise ValueError("Snapshot manifest is missing files")
    entries: list[dict[str, object]] = []
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("existed"), bool):
            raise ValueError("Snapshot manifest contains an invalid file entry")
        if entry["existed"]:
            if not isinstance(entry.get("snapshot_path"), str):
                raise ValueError("Snapshot manifest file entry is missing snapshot_path")
            if not isinstance(entry.get("sha256"), str) or not entry["sha256"]:
                raise ValueError("Snapshot manifest file entry is missing sha256")
        entries.append(entry)
    return entries


def _require_relative_to(path: Path, root: Path, *, label: str) -> None:
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} is outside snapshot directory: {path}") from exc


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
