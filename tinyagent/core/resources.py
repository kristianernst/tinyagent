"""Small explicit resource loading snapshot."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tinyagent.core.context_sources import ContextSource
from tinyagent.core.extensions import Extension, load_extension_file
from tinyagent.core.memory import PersistentMemorySource
from tinyagent.core.skills import SkillSource, default_skill_sources

WorkspaceTrust = Literal["trusted", "untrusted"]


@dataclass(frozen=True)
class LoadedResources:
    extensions: tuple[Extension, ...] = ()
    skill_sources: tuple[SkillSource, ...] | None = None
    context_sources: tuple[ContextSource, ...] = ()


@dataclass(frozen=True)
class ResourceLoaderConfig:
    no_discovery: bool = False
    memory_enabled: bool = False
    trust: WorkspaceTrust = "untrusted"
    extension_paths: tuple[Path, ...] = ()
    allow_extension_paths: bool = False


class ResourceLoader:
    def __init__(self, config: ResourceLoaderConfig | None = None) -> None:
        self.config = config or ResourceLoaderConfig()

    def load(self, workspace: Path, *, profile: str) -> LoadedResources:
        del workspace
        is_tiny_pi = profile in {"tiny-pi", "pi", "minimal"}
        skills = () if self.config.no_discovery or is_tiny_pi else default_skill_sources()
        extensions = self._load_extensions()
        context_sources: tuple[ContextSource, ...] = ()
        if self.config.memory_enabled and not is_tiny_pi:
            context_sources = (PersistentMemorySource(),)
        return LoadedResources(extensions=extensions, skill_sources=skills, context_sources=context_sources)

    def _load_extensions(self) -> tuple[Extension, ...]:
        if not self.config.extension_paths:
            return ()
        if not self.config.allow_extension_paths and self.config.trust != "trusted":
            raise PermissionError("Python extension paths require a trusted workspace or explicit extension allowance.")
        return tuple(load_extension_file(path) for path in self.config.extension_paths)
