"""Skill data types."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SkillRef:
    id: str
    name: str
    description: str
    source: str
    path: str
    tags: tuple[str, ...] = ()
    enabled: bool = True
    trust: str = "untrusted"
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class LoadedSkill:
    ref: SkillRef
    markdown: str
    files: tuple[str, ...]
    truncated: bool = False
    token_estimate: int = 0
    warnings: tuple[str, ...] = ()


class SkillSource(Protocol):
    name: str

    def list_skills(self, workspace: Path) -> Sequence[SkillRef]: ...

    def load_skill(self, skill_id: str, workspace: Path) -> LoadedSkill: ...


@dataclass(frozen=True)
class SkillCatalogue:
    skills: tuple[SkillRef, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
