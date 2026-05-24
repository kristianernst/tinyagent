"""Native shell sandbox backend helpers."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

NetworkMode = Literal["deny", "ask", "allow"]
SandboxBackend = Literal["none", "docker", "podman", "seatbelt", "landlock_seccomp", "wsl2"]


@dataclass(frozen=True)
class NativeSandboxConfig:
    backend: SandboxBackend
    read_roots: tuple[Path, ...]
    writable_roots: tuple[Path, ...]
    denied_paths: tuple[Path, ...]
    network_mode: NetworkMode


def detect_native_backend() -> SandboxBackend | None:
    if platform.system() == "Darwin" and _seatbelt_available():
        return "seatbelt"
    return None


def native_backend_version(backend: SandboxBackend) -> str:
    if backend == "seatbelt" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    return ""


def build_native_command(config: NativeSandboxConfig, cmd: str) -> list[str]:
    if config.backend != "seatbelt":
        raise ValueError(f"Unsupported native sandbox backend: {config.backend}")
    return ["sandbox-exec", "-p", seatbelt_profile(config), "/bin/sh", "-c", cmd]


def seatbelt_profile(config: NativeSandboxConfig) -> str:
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        '(allow file-read* (literal "/bin/sh"))',
        '(allow file-read* (literal "/dev/null"))',
        '(allow file-read* (literal "/dev/urandom"))',
        '(allow file-read* (subpath "/usr/lib"))',
        '(allow file-read* (subpath "/System/Library"))',
    ]
    if config.network_mode == "allow":
        lines.append("(allow network*)")
    else:
        lines.append("(deny network*)")
    for root in config.read_roots:
        lines.append(f'(allow file-read* (subpath "{_escape(root)}"))')
    for root in config.writable_roots:
        lines.append(f'(allow file-write* (subpath "{_escape(root)}"))')
    for path in config.denied_paths:
        lines.append(f'(deny file-write* (subpath "{_escape(path)}"))')
    return "\n".join(lines)


def _escape(path: Path) -> str:
    return str(path.expanduser().resolve()).replace("\\", "\\\\").replace('"', '\\"')


def _seatbelt_available() -> bool:
    sandbox_exec = shutil.which("sandbox-exec")
    if not sandbox_exec:
        return False
    try:
        result = subprocess.run(
            [sandbox_exec, "-p", _seatbelt_smoke_profile(), "/usr/bin/true"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _seatbelt_smoke_profile() -> str:
    return "\n".join(
        [
            "(version 1)",
            "(deny default)",
            "(allow process*)",
            '(allow file-read* (literal "/usr/bin/true"))',
            '(allow file-read* (literal "/dev/null"))',
            '(allow file-read* (subpath "/usr/lib"))',
            '(allow file-read* (subpath "/System/Library"))',
        ]
    )
