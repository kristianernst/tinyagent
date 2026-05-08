"""Minimal explicit extension host over hooks, tools, skills, and context sources."""

from __future__ import annotations

import importlib.util
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from tinyagent.core.context_sources import ContextSource
from tinyagent.core.contracts import Tool
from tinyagent.core.hooks import TinyHook
from tinyagent.core.skills import SkillSource


@dataclass(frozen=True)
class ExtensionInfo:
    name: str
    version: str = ""
    description: str = ""
    permissions: tuple[str, ...] = ()


class Extension(Protocol):
    name: str

    def hooks(self) -> Sequence[TinyHook]: ...

    def tools(self) -> Sequence[Tool]: ...

    def skills(self) -> Sequence[SkillSource]: ...

    def context_sources(self) -> Sequence[ContextSource]: ...


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

    def skills(self) -> tuple[SkillSource, ...]:
        sources: list[SkillSource] = []
        for extension in self.extensions:
            method = getattr(extension, "skills", None)
            if callable(method):
                sources.extend(method())
        return tuple(sources)

    def context_sources(self) -> tuple[ContextSource, ...]:
        sources: list[ContextSource] = []
        for extension in self.extensions:
            method = getattr(extension, "context_sources", None)
            if callable(method):
                sources.extend(method())
        return tuple(sources)

    def info(self) -> tuple[ExtensionInfo, ...]:
        info: list[ExtensionInfo] = []
        for extension in self.extensions:
            method = getattr(extension, "info", None)
            if callable(method):
                try:
                    declared = method()
                except Exception as exc:
                    info.append(
                        ExtensionInfo(
                            name=str(getattr(extension, "name", type(extension).__name__)),
                            description=f"extension info unavailable: {exc}",
                        )
                    )
                    continue
                if isinstance(declared, ExtensionInfo):
                    info.append(declared)
                    continue
            info.append(ExtensionInfo(name=str(getattr(extension, "name", type(extension).__name__))))
        return tuple(info)


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
