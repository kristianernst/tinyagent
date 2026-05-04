"""Minimal explicit extension host over hooks and tools."""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from agentd.contracts import Tool
from agentd.hooks import TinyHook


class Extension(Protocol):
    name: str

    def hooks(self) -> Sequence[TinyHook]: ...

    def tools(self) -> Sequence[Tool]: ...


class ExtensionHost:
    def __init__(self, extensions: Sequence[Extension] = ()) -> None:
        self.extensions = tuple(extensions)

    def hooks(self) -> tuple[TinyHook, ...]:
        hooks: list[TinyHook] = []
        for extension in self.extensions:
            method = getattr(extension, "hooks", None)
            if callable(method):
                hooks.extend(method())
        return tuple(hooks)

    def tools(self) -> tuple[Tool, ...]:
        tools: list[Tool] = []
        for extension in self.extensions:
            method = getattr(extension, "tools", None)
            if callable(method):
                tools.extend(method())
        return tuple(tools)


def load_extension_file(path: Path) -> Extension:
    """Load one explicit Python extension file with an `extension` object."""

    resolved = path.expanduser().resolve()
    spec = importlib.util.spec_from_file_location(f"tinyagent_extension_{resolved.stem}", resolved)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load extension: {resolved}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    extension = getattr(module, "extension", None)
    if extension is None:
        raise ValueError(f"Extension file must define `extension`: {resolved}")
    return extension
