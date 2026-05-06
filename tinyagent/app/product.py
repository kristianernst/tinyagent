"""Product-level home, config, and doctor helpers."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tomllib
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from tinyagent import __version__
from tinyagent.core.events import utc_now
from tinyagent.core.ids import validate_run_id

DEFAULT_HOME = Path("~/.tinyagent")
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProductHome:
    root: Path

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ProductHome:
        source = env if env is not None else os.environ
        root = Path(source.get("TINYAGENT_HOME") or DEFAULT_HOME).expanduser().resolve()
        return cls(root)

    @property
    def config_path(self) -> Path:
        return self.root / "config.toml"

    @property
    def version_path(self) -> Path:
        return self.root / "version.json"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.version_path.exists():
            now = utc_now().isoformat().replace("+00:00", "Z")
            payload = {
                "schema_version": SCHEMA_VERSION,
                "created_at": now,
                "updated_at": now,
                "tinyagent_version": __version__,
            }
            self.version_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        data = tomllib.loads(self.config_path.read_text())
        if not isinstance(data, dict):
            raise ValueError("config.toml must contain a TOML table")
        return data

    @property
    def workspaces_dir(self) -> Path:
        return self.root / "workspaces"


@dataclass(frozen=True)
class WorkspaceRecord:
    workspace_id: str
    name: str
    root: str
    kind: str
    git_root: str | None
    git_remote: str | None
    trust: str = "untrusted"
    default_profile: str = "apex-coder"
    default_provider: str = "fake"
    write_policy: str = "workspace"
    created_at: str = ""
    updated_at: str = ""
    last_opened_at: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkspaceStore:
    def __init__(self, home: ProductHome) -> None:
        self.home = home

    def register(
        self,
        root: Path,
        *,
        name: str | None = None,
        trust: str = "untrusted",
        default_provider: str | None = None,
    ) -> WorkspaceRecord:
        self.home.ensure()
        resolved = root.expanduser().resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError(f"Workspace does not exist or is not a directory: {resolved}")
        git_root = _git_output(resolved, ["rev-parse", "--show-toplevel"])
        git_remote = _git_output(resolved, ["config", "--get", "remote.origin.url"]) if git_root else None
        identity_root = str(Path(git_root).resolve()) if git_root else str(resolved)
        canonical_root = identity_root if git_root else str(resolved)
        workspace_id = workspace_id_for(identity_root, git_remote)
        path = self.workspace_path(workspace_id)
        existing = self.load(workspace_id) if (path / "workspace.json").exists() else None
        now = _now()
        record = WorkspaceRecord(
            workspace_id=workspace_id,
            name=name or (existing.name if existing else Path(identity_root).name or "workspace"),
            root=canonical_root,
            kind="git" if git_root else "directory",
            git_root=identity_root if git_root else None,
            git_remote=git_remote,
            trust=trust if trust != "untrusted" or existing is None else existing.trust,
            default_profile=existing.default_profile if existing else "apex-coder",
            default_provider=default_provider or (existing.default_provider if existing else "fake"),
            write_policy=existing.write_policy if existing else "workspace",
            created_at=existing.created_at if existing else now,
            updated_at=now,
            last_opened_at=now,
        )
        path.mkdir(parents=True, exist_ok=True)
        (path / "workspace.json").write_text(json.dumps(record.to_json_dict(), indent=2, sort_keys=True) + "\n")
        return record

    def load(self, workspace_id: str) -> WorkspaceRecord:
        _validate_workspace_id(workspace_id)
        data = json.loads((self.workspace_path(workspace_id) / "workspace.json").read_text())
        if not isinstance(data, dict):
            raise ValueError(f"invalid workspace record: {workspace_id}")
        return WorkspaceRecord(**data)

    def list(self) -> list[WorkspaceRecord]:
        if not self.home.workspaces_dir.exists():
            return []
        records: list[WorkspaceRecord] = []
        for path in sorted(self.home.workspaces_dir.iterdir()):
            if not path.is_dir() or not (path / "workspace.json").exists():
                continue
            try:
                records.append(self.load(path.name))
            except (OSError, ValueError, json.JSONDecodeError, TypeError):
                continue
        return sorted(records, key=lambda item: item.last_opened_at or item.updated_at, reverse=True)

    def remove(self, workspace_id: str) -> bool:
        path = self.workspace_path(workspace_id)
        if not (path / "workspace.json").exists():
            return False
        (path / "workspace.json").unlink()
        return True

    def workspace_path(self, workspace_id: str) -> Path:
        _validate_workspace_id(workspace_id)
        return self.home.workspaces_dir / workspace_id

    def run_root(self, workspace_id: str) -> Path:
        return self.workspace_path(workspace_id) / "runs"

    def find_run(self, run_id: str) -> Path:
        validate_run_id(run_id)
        for record in self.list():
            path = self.run_root(record.workspace_id) / run_id
            if (path / "events.jsonl").exists():
                return path
        raise FileNotFoundError(f"run not found in product home: {run_id}")


def workspace_id_for(root: str, git_remote: str | None = None) -> str:
    payload = f"{root}\0{git_remote or ''}"
    return "ws_" + sha256(payload.encode()).hexdigest()[:16]


def _validate_workspace_id(workspace_id: str) -> None:
    if not workspace_id or "/" in workspace_id or "\\" in workspace_id or workspace_id.startswith("."):
        raise ValueError(f"invalid workspace_id: {workspace_id}")


def render_doctor(home: ProductHome, *, workspace: Path, provider: str, port: int) -> tuple[str, bool]:
    lines = ["Tinyagent Doctor", "", f"version: {__version__}", f"home: {home.root}"]
    ok = True

    try:
        home.ensure()
    except OSError as exc:
        lines.append(f"home writable: fail ({exc})")
        lines.append("version.json: fail")
        lines.append("")
        lines.append("status: failed")
        return "\n".join(lines) + "\n", False

    ok = _check(lines, "home writable", _is_writable(home.root)) and ok
    ok = _check(lines, "version.json", _valid_version(home.version_path)) and ok

    try:
        home.load_config()
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        lines.append(f"config: fail ({exc})")
        ok = False
    else:
        suffix = str(home.config_path) if home.config_path.exists() else "not found; using defaults"
        lines.append(f"config: ok ({suffix})")

    resolved_workspace = workspace.expanduser().resolve()
    ok = _check(lines, "workspace", resolved_workspace.is_dir(), str(resolved_workspace)) and ok
    for tool in ("rg", "git", "python3", "python", "sed"):
        ok = _check(lines, f"tool {tool}", shutil.which(tool) is not None) and ok
    ok = _check(lines, f"port {port}", _port_available(port)) and ok

    if provider == "openai-compatible":
        has_key = bool(os.environ.get("TINYAGENT_MODEL_API_KEY"))
        has_model = bool(os.environ.get("TINYAGENT_MODEL_NAME"))
        ok = _check(lines, "provider api key", has_key, "TINYAGENT_MODEL_API_KEY") and ok
        ok = _check(lines, "provider model", has_model, "TINYAGENT_MODEL_NAME") and ok
    else:
        lines.append(f"provider: ok ({provider})")

    lines.append("")
    lines.append(f"status: {'ok' if ok else 'failed'}")
    return "\n".join(lines) + "\n", ok


def _check(lines: list[str], label: str, passed: bool, detail: str = "") -> bool:
    status = "ok" if passed else "fail"
    suffix = f" ({detail})" if detail else ""
    lines.append(f"{label}: {status}{suffix}")
    return passed


def _is_writable(path: Path) -> bool:
    try:
        probe = path / ".doctor-write-test"
        probe.write_text("")
        probe.unlink()
    except OSError:
        return False
    return True


def _valid_version(path: Path) -> bool:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return data.get("schema_version") == SCHEMA_VERSION


def _port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))
    except (OSError, OverflowError):
        return False
    return True


def _git_output(root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")
