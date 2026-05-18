"""Product update checks and versioned install switching."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import urlopen

from tinyagent import __version__
from tinyagent.app.product import ProductHome
from tinyagent.core.events import utc_now

DEFAULT_UPDATE_CHANNEL = "alpha"
DEFAULT_UPDATE_BASE_URL = "https://releases.tinyagent.dev"
UPDATE_STATE_SCHEMA_VERSION = 1
MANAGED_INSTALL_KINDS = frozenset({"standalone", "managed"})


@dataclass(frozen=True)
class UpdateArtifact:
    platform: str
    url: str
    sha256: str
    size: int | None = None
    kind: str = "archive"
    expected_files: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> UpdateArtifact:
        platform_value = str(data.get("platform") or "").strip()
        url = str(data.get("url") or "").strip()
        digest = str(data.get("sha256") or "").strip().lower()
        if not platform_value:
            raise ValueError("update artifact platform is required")
        if not url:
            raise ValueError("update artifact url is required")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"update artifact sha256 is invalid for {platform_value}")
        expected = data.get("expected_files") or ()
        if not isinstance(expected, list):
            raise ValueError("update artifact expected_files must be a list")
        return cls(
            platform=platform_value,
            url=url,
            sha256=digest,
            size=int(data["size"]) if data.get("size") is not None else None,
            kind=str(data.get("kind") or "archive"),
            expected_files=tuple(str(item) for item in expected),
        )

    def to_json_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "platform": self.platform,
            "url": self.url,
            "sha256": self.sha256,
            "kind": self.kind,
            "expected_files": list(self.expected_files),
        }
        if self.size is not None:
            payload["size"] = self.size
        return payload


@dataclass(frozen=True)
class UpdateManifest:
    channel: str
    version: str
    artifacts: tuple[UpdateArtifact, ...]
    published_at: str = ""
    notes: str = ""
    schema: int = 1

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> UpdateManifest:
        channel = str(data.get("channel") or "").strip()
        version = str(data.get("version") or "").strip()
        artifacts_data = data.get("artifacts")
        if not channel:
            raise ValueError("update manifest channel is required")
        if not version:
            raise ValueError("update manifest version is required")
        if not isinstance(artifacts_data, list) or not artifacts_data:
            raise ValueError("update manifest artifacts are required")
        artifacts = tuple(UpdateArtifact.from_json(item) for item in artifacts_data if isinstance(item, dict))
        if not artifacts:
            raise ValueError("update manifest artifacts are invalid")
        return cls(
            schema=int(data.get("schema") or 1),
            channel=channel,
            version=version,
            published_at=str(data.get("published_at") or ""),
            notes=str(data.get("notes") or ""),
            artifacts=artifacts,
        )

    def artifact_for(self, target_platform: str) -> UpdateArtifact:
        for artifact in self.artifacts:
            if artifact.platform == target_platform:
                return artifact
        for artifact in self.artifacts:
            if artifact.platform == "any":
                return artifact
        raise ValueError(f"no update artifact for platform: {target_platform}")

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "channel": self.channel,
            "version": self.version,
            "published_at": self.published_at,
            "notes": self.notes,
            "artifacts": [artifact.to_json_dict() for artifact in self.artifacts],
        }


@dataclass(frozen=True)
class UpdateStatus:
    current_version: str
    channel: str
    install_kind: str
    manifest_source: str
    checked_at: str
    latest_version: str = ""
    available: bool = False
    reason: str = "not_checked"
    platform: str = ""
    artifact: UpdateArtifact | None = None
    active_version: str = ""
    previous_version: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "current_version": self.current_version,
            "channel": self.channel,
            "install_kind": self.install_kind,
            "manifest_source": self.manifest_source,
            "checked_at": self.checked_at,
            "latest_version": self.latest_version,
            "available": self.available,
            "reason": self.reason,
            "platform": self.platform,
            "artifact": self.artifact.to_json_dict() if self.artifact else None,
            "active_version": self.active_version,
            "previous_version": self.previous_version,
        }


class UpdateManager:
    def __init__(
        self,
        home: ProductHome,
        *,
        current_version: str = __version__,
        install_kind: str | None = None,
    ) -> None:
        self.home = home
        self.current_version = current_version
        self.install_kind = install_kind or detect_install_kind(home)

    @property
    def state_path(self) -> Path:
        return self.home.updates_dir / "state.json"

    def channel(self, channel: str | None = None) -> str:
        if channel:
            return channel
        env_channel = os.environ.get("TINYAGENT_UPDATE_CHANNEL")
        if env_channel:
            return env_channel
        try:
            config = self.home.load_config()
        except (OSError, ValueError):
            config = {}
        updates = config.get("updates") if isinstance(config.get("updates"), dict) else {}
        return str(updates.get("channel") or DEFAULT_UPDATE_CHANNEL)

    def manifest_source(self, channel: str | None = None, source: str | None = None) -> str:
        if source:
            return source
        configured = self.configured_manifest_source()
        if configured:
            return configured
        resolved_channel = self.channel(channel)
        return f"{DEFAULT_UPDATE_BASE_URL}/{resolved_channel}/manifest.json"

    def configured_manifest_source(self) -> str:
        env_source = os.environ.get("TINYAGENT_UPDATE_MANIFEST")
        if env_source:
            return env_source
        try:
            config = self.home.load_config()
        except (OSError, ValueError):
            config = {}
        updates = config.get("updates") if isinstance(config.get("updates"), dict) else {}
        configured = updates.get("manifest_url") or updates.get("manifest")
        if configured:
            return str(configured)
        return ""

    def status(self) -> UpdateStatus:
        state = self._load_state()
        channel = str(state.get("channel") or self.channel())
        return UpdateStatus(
            current_version=self.current_version,
            channel=channel,
            install_kind=self.install_kind,
            manifest_source=str(state.get("manifest_source") or ""),
            checked_at=str(state.get("checked_at") or ""),
            latest_version=str(state.get("latest_version") or ""),
            available=bool(state.get("available")),
            reason=str(state.get("reason") or "not_checked"),
            platform=str(state.get("platform") or platform_tag()),
            artifact=UpdateArtifact.from_json(state["artifact"]) if isinstance(state.get("artifact"), dict) else None,
            active_version=str(state.get("active_version") or self.active_version()),
            previous_version=str(state.get("previous_version") or ""),
        )

    def check(self, *, channel: str | None = None, manifest_source: str | None = None) -> UpdateStatus:
        resolved_channel = self.channel(channel)
        source = self.manifest_source(resolved_channel, manifest_source)
        manifest = load_manifest(source)
        if manifest.channel != resolved_channel:
            raise ValueError(f"manifest channel {manifest.channel!r} does not match requested channel {resolved_channel!r}")
        target_platform = platform_tag()
        artifact = manifest.artifact_for(target_platform)
        available = version_greater(manifest.version, self.current_version)
        reason = "available" if available else "current"
        status = UpdateStatus(
            current_version=self.current_version,
            channel=resolved_channel,
            install_kind=self.install_kind,
            manifest_source=source,
            checked_at=_now(),
            latest_version=manifest.version,
            available=available,
            reason=reason,
            platform=target_platform,
            artifact=artifact,
            active_version=self.active_version(),
            previous_version=str(self._load_state().get("previous_version") or ""),
        )
        self._write_state(status.to_json_dict())
        return status

    def auto_check_if_configured(self) -> UpdateStatus:
        source = self.configured_manifest_source()
        if not source:
            return self.status()
        state = self._load_state()
        checked_at = str(state.get("checked_at") or "")
        if checked_at and _age_seconds(checked_at) < self.auto_check_interval_seconds():
            return self.status()
        return self.check(channel=self.channel(), manifest_source=source)

    def auto_check_interval_seconds(self) -> int:
        env_value = os.environ.get("TINYAGENT_UPDATE_AUTO_CHECK_HOURS")
        if env_value:
            try:
                return max(1, int(float(env_value) * 3600))
            except ValueError:
                return 24 * 3600
        try:
            config = self.home.load_config()
        except (OSError, ValueError):
            config = {}
        updates = config.get("updates") if isinstance(config.get("updates"), dict) else {}
        value = updates.get("auto_check_interval_hours")
        if value is None:
            return 24 * 3600
        try:
            return max(1, int(float(value) * 3600))
        except (TypeError, ValueError):
            return 24 * 3600

    def apply(
        self,
        *,
        channel: str | None = None,
        manifest_source: str | None = None,
        force_managed: bool = False,
    ) -> UpdateStatus:
        status = self.check(channel=channel, manifest_source=manifest_source)
        if not status.available:
            return status
        if self.install_kind not in MANAGED_INSTALL_KINDS and not force_managed:
            raise ValueError(
                f"update apply requires a standalone tinyagent install; current install kind is {self.install_kind}. "
                "Use your package manager for this install."
            )
        if status.artifact is None:
            raise ValueError("update artifact is missing")
        artifact_source = resolve_artifact_source(status.manifest_source, status.artifact.url)
        archive = read_source_bytes(artifact_source)
        digest = sha256(archive).hexdigest()
        if digest != status.artifact.sha256:
            raise ValueError(f"update artifact checksum mismatch: expected {status.artifact.sha256}, got {digest}")
        previous_version = self.active_version()
        version_dir = self.install_archive(status.latest_version, archive, status.artifact)
        self.switch_current(status.latest_version)
        self.write_install_receipt(kind="standalone", active_version=status.latest_version)
        applied = UpdateStatus(
            current_version=self.current_version,
            channel=status.channel,
            install_kind="standalone",
            manifest_source=status.manifest_source,
            checked_at=_now(),
            latest_version=status.latest_version,
            available=False,
            reason="applied",
            platform=status.platform,
            artifact=status.artifact,
            active_version=version_dir.name,
            previous_version=previous_version,
        )
        self._write_state(applied.to_json_dict())
        return applied

    def rollback(self) -> UpdateStatus:
        state = self._load_state()
        previous = str(state.get("previous_version") or "")
        if not previous:
            raise ValueError("no previous tinyagent version recorded for rollback")
        if not (self.home.versions_dir / previous).is_dir():
            raise ValueError(f"rollback version is missing: {previous}")
        active = self.active_version()
        self.switch_current(previous)
        self.write_install_receipt(kind="standalone", active_version=previous)
        status = UpdateStatus(
            current_version=self.current_version,
            channel=str(state.get("channel") or self.channel()),
            install_kind="standalone",
            manifest_source=str(state.get("manifest_source") or ""),
            checked_at=_now(),
            latest_version=str(state.get("latest_version") or previous),
            available=False,
            reason="rolled_back",
            platform=str(state.get("platform") or platform_tag()),
            artifact=UpdateArtifact.from_json(state["artifact"]) if isinstance(state.get("artifact"), dict) else None,
            active_version=previous,
            previous_version=active,
        )
        self._write_state(status.to_json_dict())
        return status

    def install_archive(self, version: str, archive: bytes, artifact: UpdateArtifact) -> Path:
        self.home.versions_dir.mkdir(parents=True, exist_ok=True)
        self.home.updates_dir.mkdir(parents=True, exist_ok=True)
        staging = self.home.updates_dir / "staging" / version
        destination = self.home.versions_dir / version
        if destination.exists():
            raise ValueError(f"version is already installed: {version}")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True, exist_ok=True)
        archive_path = staging / "artifact"
        archive_path.write_bytes(archive)
        extracted = staging / "extracted"
        extracted.mkdir()
        extract_archive(archive_path, extracted)
        payload = payload_root(extracted)
        for relative in artifact.expected_files:
            if not _safe_child(payload, relative).exists():
                raise ValueError(f"update artifact is missing expected file: {relative}")
        temporary_destination = self.home.versions_dir / f".{version}.tmp"
        if temporary_destination.exists():
            shutil.rmtree(temporary_destination)
        shutil.copytree(payload, temporary_destination)
        os.replace(temporary_destination, destination)
        shutil.rmtree(staging)
        return destination

    def switch_current(self, version: str) -> None:
        target = self.home.versions_dir / version
        if not target.is_dir():
            raise ValueError(f"installed version is missing: {version}")
        self.home.root.mkdir(parents=True, exist_ok=True)
        temporary = self.home.root / ".current.tmp"
        if temporary.exists() or temporary.is_symlink():
            if temporary.is_dir() and not temporary.is_symlink():
                shutil.rmtree(temporary)
            else:
                temporary.unlink()
        try:
            temporary.symlink_to(target, target_is_directory=True)
            os.replace(temporary, self.home.current_path)
        except OSError:
            if temporary.exists() or temporary.is_symlink():
                temporary.unlink()
            (self.home.root / "current.json").write_text(json.dumps({"version": version, "path": str(target)}, indent=2) + "\n")

    def active_version(self) -> str:
        receipt = self._load_install_receipt()
        if isinstance(receipt.get("active_version"), str):
            return str(receipt["active_version"])
        if self.home.current_path.is_symlink():
            return self.home.current_path.resolve().name
        current_json = self.home.root / "current.json"
        if current_json.exists():
            try:
                data = json.loads(current_json.read_text())
            except json.JSONDecodeError:
                return ""
            return str(data.get("version") or "")
        return ""

    def write_install_receipt(self, *, kind: str, active_version: str = "") -> None:
        self.home.ensure()
        payload = {
            "schema_version": 1,
            "kind": kind,
            "active_version": active_version,
            "updated_at": _now(),
        }
        self.home.install_receipt_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        self.install_kind = kind

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, status: dict[str, Any]) -> None:
        self.home.updates_dir.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": UPDATE_STATE_SCHEMA_VERSION, **status}
        self.state_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def _load_install_receipt(self) -> dict[str, Any]:
        if not self.home.install_receipt_path.exists():
            return {}
        try:
            data = json.loads(self.home.install_receipt_path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}


def detect_install_kind(home: ProductHome) -> str:
    env_value = os.environ.get("TINYAGENT_INSTALL_KIND")
    if env_value:
        return env_value
    if home.install_receipt_path.exists():
        try:
            data = json.loads(home.install_receipt_path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        kind = data.get("kind") if isinstance(data, dict) else None
        if isinstance(kind, str) and kind:
            return kind
    source_root = Path(__file__).resolve()
    if any((parent / ".git").exists() for parent in source_root.parents[:6]):
        return "source"
    executable = Path(sys.argv[0]).name
    if executable in {"pipx", "uv"}:
        return executable
    return "python-package"


def version_payload(home: ProductHome) -> dict[str, Any]:
    manager = UpdateManager(home)
    status = manager.status()
    return {
        "version": __version__,
        "channel": manager.channel(),
        "install_kind": manager.install_kind,
        "home": str(home.root),
        "current": str(home.current_path),
        "active_version": status.active_version,
        "update": status.to_json_dict(),
    }


def install_shims(home: ProductHome, bin_dir: Path) -> list[Path]:
    resolved_bin = bin_dir.expanduser().resolve()
    resolved_bin.mkdir(parents=True, exist_ok=True)
    shims: list[Path] = []
    for name in ("tinyagent", "tinyagent-tui"):
        shim = resolved_bin / name
        target = home.current_path / "bin" / name
        shim.write_text(f"#!/bin/sh\nexec {json.dumps(str(target))} \"$@\"\n")
        shim.chmod(0o755)
        shims.append(shim)
    return shims


def render_update_status(status: UpdateStatus) -> str:
    lines = [
        f"channel: {status.channel}",
        f"current_version: {status.current_version}",
        f"install_kind: {status.install_kind}",
    ]
    if status.latest_version:
        lines.append(f"latest_version: {status.latest_version}")
    if status.active_version:
        lines.append(f"active_version: {status.active_version}")
    lines.append(f"status: {status.reason}")
    if status.available:
        lines.append(f"update_available: {status.latest_version}")
    if status.manifest_source:
        lines.append(f"manifest: {status.manifest_source}")
    return "\n".join(lines) + "\n"


def load_manifest(source: str) -> UpdateManifest:
    data = json.loads(read_source_bytes(source).decode())
    if not isinstance(data, dict):
        raise ValueError("update manifest must be a JSON object")
    return UpdateManifest.from_json(data)


def read_source_bytes(source: str) -> bytes:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        with urlopen(source, timeout=20) as response:  # noqa: S310 - updater only fetches user/configured release URLs.
            return response.read()
    path = Path(parsed.path if parsed.scheme == "file" else source).expanduser()
    return path.read_bytes()


def resolve_artifact_source(manifest_source: str, artifact_url: str) -> str:
    parsed = urlparse(artifact_url)
    if parsed.scheme or Path(artifact_url).is_absolute():
        return artifact_url
    manifest_parsed = urlparse(manifest_source)
    if manifest_parsed.scheme in {"http", "https"}:
        return urljoin(manifest_source, artifact_url)
    base = Path(manifest_parsed.path if manifest_parsed.scheme == "file" else manifest_source).expanduser().parent
    return str(base / artifact_url)


def platform_tag() -> str:
    system = sys.platform
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"x86_64", "amd64"} else machine
    if system == "darwin":
        os_name = "darwin"
    elif system.startswith("linux"):
        os_name = "linux"
    elif system.startswith("win"):
        os_name = "windows"
    else:
        os_name = system
    return f"{os_name}-{arch}"


def extract_archive(archive_path: Path, destination: Path) -> None:
    if tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path) as archive:
            for member in archive.getmembers():
                if member.issym() or member.islnk():
                    raise ValueError("update artifacts may not contain links")
                _safe_child(destination, member.name)
            archive.extractall(destination, filter="data")
        return
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                _safe_child(destination, name)
            archive.extractall(destination)
        return
    raise ValueError("update artifact must be a tar or zip archive")


def payload_root(extracted: Path) -> Path:
    children = [item for item in extracted.iterdir() if item.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extracted


def version_greater(left: str, right: str) -> bool:
    return _version_key(left) > _version_key(right)


def _version_key(value: str) -> tuple[int, int, int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(a|b|rc)(\d+)|[-.]?(alpha|beta|rc)\.?(\d+)?)?", value)
    if not match:
        return (0, 0, 0, -4, 0)
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    short_phase = match.group(4)
    short_num = match.group(5)
    long_phase = match.group(6)
    long_num = match.group(7)
    phase = short_phase or long_phase or ""
    number = int(short_num or long_num or 0)
    order = {"a": -3, "alpha": -3, "b": -2, "beta": -2, "rc": -1, "": 0}[phase]
    return (major, minor, patch, order, number)


def _safe_child(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"update artifact path escapes destination: {relative}") from exc
    return target


def _now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def _age_seconds(value: str) -> float:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (utc_now() - parsed).total_seconds())
