"""Container sandbox command construction."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CONTAINER_WORKDIR = "/workspace"
CONTAINER_HOME = "/home/tinyagent"
DEFAULT_CONTAINER_IMAGE = "python:3.12-slim"
NetworkMode = Literal["deny", "ask", "allow"]
SandboxBackend = Literal["none", "docker", "podman", "seatbelt", "landlock_seccomp", "wsl2"]


@dataclass(frozen=True)
class ContainerSandboxConfig:
    backend: SandboxBackend
    image: str
    workspace_host: Path
    home_host: Path
    cidfile_host: Path
    network_mode: NetworkMode
    uid: int
    gid: int


def detect_container_backend() -> SandboxBackend | None:
    image = default_container_image()
    for backend in ("docker", "podman"):
        if not shutil.which(backend):
            continue
        if _backend_available(backend) and _image_available(backend, image):
            return backend
    return None


def container_backend_version(backend: SandboxBackend) -> str:
    if backend not in {"docker", "podman"}:
        return ""
    try:
        result = subprocess.run([backend, "--version"], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def default_container_image() -> str:
    image = os.environ.get("TINYAGENT_CONTAINER_IMAGE", DEFAULT_CONTAINER_IMAGE)
    validate_container_image(image)
    return image


def validate_container_image(image: str) -> None:
    if not image or image.startswith("-") or any(char.isspace() for char in image):
        raise ValueError("TINYAGENT_CONTAINER_IMAGE must be a non-empty image reference and cannot start with '-'")


def build_container_command(config: ContainerSandboxConfig, command: str) -> list[str]:
    if config.backend not in {"docker", "podman"}:
        raise ValueError(f"Unsupported container backend: {config.backend}")
    network_args = _network_args(config.backend, config.network_mode)
    bootstrap = "git config --global --add safe.directory /workspace >/dev/null 2>&1 || true\n" + command
    return [
        config.backend,
        "run",
        "--rm",
        "--interactive",
        "--pull",
        "never",
        "--cidfile",
        str(config.cidfile_host),
        "--workdir",
        CONTAINER_WORKDIR,
        "--env",
        f"HOME={CONTAINER_HOME}",
        "--env",
        "TINYAGENT_SANDBOX=container",
        "--user",
        f"{config.uid}:{config.gid}",
        "--volume",
        f"{config.workspace_host}:{CONTAINER_WORKDIR}:rw",
        "--volume",
        f"{config.home_host}:{CONTAINER_HOME}:rw",
        "--tmpfs",
        f"{CONTAINER_WORKDIR}/.tinyagent:rw,noexec,nosuid,size=64m",
        *network_args,
        config.image,
        "sh",
        "-lc",
        bootstrap,
    ]


def _network_args(backend: SandboxBackend, mode: NetworkMode) -> list[str]:
    del backend
    if mode == "deny":
        return ["--network", "none"]
    if mode == "allow":
        return []
    return ["--network", "none"]


def _backend_available(backend: str) -> bool:
    try:
        result = subprocess.run([backend, "info"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _image_available(backend: str, image: str) -> bool:
    try:
        result = subprocess.run([backend, "image", "inspect", image], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
