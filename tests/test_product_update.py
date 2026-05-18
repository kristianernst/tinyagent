from __future__ import annotations

import json
import tarfile
from hashlib import sha256
from pathlib import Path

import pytest

from tinyagent.app.product import ProductHome
from tinyagent.app.update import UpdateManager, install_shims, platform_tag, version_greater


def test_update_check_reads_alpha_manifest_and_reports_available(tmp_path) -> None:
    manifest = _write_manifest(tmp_path, "0.1.0a1")
    manager = UpdateManager(ProductHome(tmp_path / "home"), current_version="0.1.0a0", install_kind="source")

    status = manager.check(manifest_source=str(manifest))

    assert status.channel == "alpha"
    assert status.latest_version == "0.1.0a1"
    assert status.available is True
    assert status.reason == "available"
    assert status.artifact is not None
    assert status.artifact.platform == platform_tag()


def test_update_apply_installs_versioned_payload_and_rollback_switches_previous(tmp_path) -> None:
    home = ProductHome(tmp_path / "home")
    manager = UpdateManager(home, current_version="0.1.0a0", install_kind="standalone")
    previous = home.versions_dir / "0.1.0a0"
    (previous / "bin").mkdir(parents=True)
    (previous / "bin" / "tinyagent").write_text("old\n")
    manager.write_install_receipt(kind="standalone", active_version="0.1.0a0")
    manager.switch_current("0.1.0a0")
    manifest = _write_manifest(tmp_path, "0.1.0a1")

    applied = manager.apply(manifest_source=str(manifest))

    assert applied.reason == "applied"
    assert applied.active_version == "0.1.0a1"
    assert applied.previous_version == "0.1.0a0"
    assert (home.current_path.resolve() / "bin" / "tinyagent").read_text() == "tinyagent 0.1.0a1\n"
    assert (home.current_path.resolve() / "tui" / "dist" / "main.js").exists()

    rolled_back = manager.rollback()

    assert rolled_back.reason == "rolled_back"
    assert rolled_back.active_version == "0.1.0a0"
    assert (home.current_path.resolve() / "bin" / "tinyagent").read_text() == "old\n"


def test_update_apply_refuses_package_managed_install(tmp_path) -> None:
    manifest = _write_manifest(tmp_path, "0.1.0a1")
    manager = UpdateManager(ProductHome(tmp_path / "home"), current_version="0.1.0a0", install_kind="python-package")

    with pytest.raises(ValueError, match="requires a standalone tinyagent install"):
        manager.apply(manifest_source=str(manifest))


def test_install_shims_target_current_payload(tmp_path) -> None:
    home = ProductHome(tmp_path / "home")
    manager = UpdateManager(home, current_version="0.1.0a0", install_kind="standalone")
    payload = home.versions_dir / "0.1.0a0"
    (payload / "bin").mkdir(parents=True)
    (payload / "bin" / "tinyagent").write_text("tinyagent\n")
    (payload / "bin" / "tinyagent-tui").write_text("tinyagent-tui\n")
    manager.switch_current("0.1.0a0")

    shims = install_shims(home, tmp_path / "bin")

    assert [path.name for path in shims] == ["tinyagent", "tinyagent-tui"]
    assert str(home.current_path / "bin" / "tinyagent") in shims[0].read_text()


def test_update_version_compare_understands_alpha_ordering() -> None:
    assert version_greater("0.1.0a1", "0.1.0a0")
    assert version_greater("0.1.0", "0.1.0a9")
    assert not version_greater("0.1.0a0", "0.1.0a0")


def _write_manifest(root: Path, version: str) -> Path:
    archive = _write_artifact(root, version)
    digest = sha256(archive.read_bytes()).hexdigest()
    manifest = {
        "schema": 1,
        "channel": "alpha",
        "version": version,
        "published_at": "2026-05-17T00:00:00Z",
        "artifacts": [
            {
                "platform": "any",
                "url": archive.name,
                "sha256": digest,
                "size": archive.stat().st_size,
                "expected_files": ["bin/tinyagent", "tui/dist/main.js"],
            },
            {
                "platform": platform_tag(),
                "url": archive.name,
                "sha256": digest,
                "size": archive.stat().st_size,
                "expected_files": ["bin/tinyagent", "tui/dist/main.js"],
            },
        ],
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def _write_artifact(root: Path, version: str) -> Path:
    payload = root / f"tinyagent-{version}"
    (payload / "bin").mkdir(parents=True)
    (payload / "tui" / "dist").mkdir(parents=True)
    (payload / "bin" / "tinyagent").write_text(f"tinyagent {version}\n")
    (payload / "bin" / "tinyagent-tui").write_text(f"tinyagent-tui {version}\n")
    (payload / "tui" / "dist" / "main.js").write_text("console.log('tinyagent tui')\n")
    archive = root / f"tinyagent-{version}.tar"
    with tarfile.open(archive, "w") as tar:
        tar.add(payload, arcname=payload.name)
    return archive
