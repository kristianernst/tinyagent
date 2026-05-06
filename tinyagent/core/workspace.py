"""Workspace boundary and worktree preparation."""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from tinyagent.core.container_sandbox import default_container_image, detect_container_backend

WorkspaceMode = Literal["auto", "worktree", "current"]
SandboxMode = Literal["none", "container", "native"]
SandboxModeInput = Literal["none", "container", "native"]
NetworkMode = Literal["deny", "ask", "allow"]
SandboxBackend = Literal["none", "docker", "podman", "seatbelt", "landlock_seccomp", "wsl2"]


@dataclass(frozen=True)
class Workspace:
    root: Path

    def resolved_root(self) -> Path:
        return self.root.expanduser().resolve()

    def resolve_path(self, path: str | Path = ".") -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return candidate.resolve()

    def contains(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
        except ValueError:
            return False
        return True


@dataclass(frozen=True)
class DirtyState:
    is_git_repo: bool = False
    has_head: bool = False
    clean: bool = True
    head: str | None = None
    branch: str | None = None
    status_short: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["status_short"] = list(self.status_short)
        return data


@dataclass(frozen=True)
class WorkspaceEnvelope:
    root: Path
    original_root: Path
    mode: WorkspaceMode
    effective_mode: Literal["worktree", "current"]
    worktree_path: Path | None = None
    git_head_before: str | None = None
    dirty_state_before: DirtyState = field(default_factory=DirtyState)
    allowed_roots: tuple[Path, ...] = ()
    sandbox_mode: SandboxMode = "none"
    sandbox_backend: SandboxBackend = "none"
    network_mode: NetworkMode = "ask"
    sandbox_enforced: bool = False

    def to_json_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "original_root": str(self.original_root),
            "mode": self.mode,
            "effective_mode": self.effective_mode,
            "worktree_path": str(self.worktree_path) if self.worktree_path else None,
            "git_head_before": self.git_head_before,
            "dirty_state_before": self.dirty_state_before.to_json_dict(),
            "allowed_roots": [str(root) for root in self.allowed_roots],
            "sandbox_mode": self.sandbox_mode,
            "sandbox_backend": self.sandbox_backend,
            "network_mode": self.network_mode,
            "sandbox_enforced": self.sandbox_enforced,
        }

    def contains(self, path: Path) -> bool:
        resolved = path.expanduser().resolve()
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False


@dataclass(frozen=True)
class PreparedWorkspace:
    workspace: Workspace
    envelope: WorkspaceEnvelope
    worktree_created: bool = False


def prepare_workspace(
    root: Path,
    *,
    mode: WorkspaceMode,
    run_id: str,
    sandbox_mode: SandboxModeInput = "none",
) -> PreparedWorkspace:
    original_root = root.expanduser().resolve()
    if not original_root.exists() or not original_root.is_dir():
        raise ValueError(f"Workspace does not exist or is not a directory: {original_root}")

    dirty = inspect_dirty_state(original_root)
    effective_mode: Literal["worktree", "current"] = "current"
    effective_root = original_root
    worktree_path: Path | None = None
    worktree_created = False
    sandbox_backend: SandboxBackend = "none"
    sandbox_enforced = False
    if sandbox_mode == "container":
        detected_backend = detect_container_backend()
        if detected_backend is None:
            image = default_container_image()
            raise ValueError(
                "sandbox-mode=container requires a usable Docker or Podman backend "
                f"with local image {image!r}; image pulls are disabled"
            )
        sandbox_backend = detected_backend
        sandbox_enforced = True
    elif sandbox_mode == "native":
        raise ValueError("sandbox-mode=native requires a native sandbox backend; no backend is configured yet")

    use_worktree = mode == "worktree" or (mode == "auto" and dirty.is_git_repo and dirty.has_head and dirty.clean)
    if use_worktree:
        if not dirty.is_git_repo or not dirty.has_head:
            raise ValueError("workspace-mode=worktree requires a git workspace with HEAD")
        if not dirty.clean:
            raise ValueError("workspace-mode=worktree requires a clean git workspace")
        worktree_path = _available_worktree_path(_worktree_path(original_root, run_id))
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        _run_git(original_root, ["worktree", "add", "--detach", str(worktree_path), "HEAD"], timeout=30)
        effective_root = worktree_path.resolve()
        effective_mode = "worktree"
        worktree_created = True

    envelope = WorkspaceEnvelope(
        root=effective_root,
        original_root=original_root,
        mode=mode,
        effective_mode=effective_mode,
        worktree_path=worktree_path,
        git_head_before=dirty.head,
        dirty_state_before=dirty,
        allowed_roots=(effective_root,),
        sandbox_mode=sandbox_mode,
        sandbox_backend=sandbox_backend,
        network_mode="deny",
        sandbox_enforced=sandbox_enforced,
    )
    return PreparedWorkspace(workspace=Workspace(effective_root), envelope=envelope, worktree_created=worktree_created)


def inspect_dirty_state(root: Path) -> DirtyState:
    inside = _git(root, ["rev-parse", "--is-inside-work-tree"])
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return DirtyState(is_git_repo=False, clean=True)

    head_result = _git(root, ["rev-parse", "--verify", "HEAD"])
    has_head = head_result.returncode == 0
    head = head_result.stdout.strip() if has_head else None
    branch_result = _git(root, ["branch", "--show-current"])
    branch = branch_result.stdout.strip() or None if branch_result.returncode == 0 else None
    status_result = _git(root, ["status", "--short"])
    status = tuple(line for line in status_result.stdout.splitlines() if line) if status_result.returncode == 0 else ()
    return DirtyState(
        is_git_repo=True,
        has_head=has_head,
        clean=not status,
        head=head,
        branch=branch,
        status_short=status,
    )


def _worktree_path(root: Path, run_id: str) -> Path:
    safe_repo = "".join(char if char.isalnum() or char in "._-" else "-" for char in root.name)
    safe_run = "".join(char if char.isalnum() or char in "._-" else "-" for char in run_id)
    return Path(tempfile.gettempdir()) / "tinyagent-worktrees" / f"{safe_repo}-{safe_run}"


def _available_worktree_path(base: Path) -> Path:
    if not base.exists():
        return base
    for index in range(1, 1000):
        candidate = base.with_name(f"{base.name}-{index}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"No available worktree path near {base}")


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10, check=False)


def _run_git(root: Path, args: list[str], *, timeout: int) -> None:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise ValueError(detail)
