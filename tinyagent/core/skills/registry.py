"""Skill registry with scope-priority deduplication."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from tinyagent.core.skills.discovery import default_skill_sources
from tinyagent.core.skills.types import LoadedSkill, SkillCatalogue, SkillRef, SkillSource


class SkillRegistry:
    def __init__(self, sources: Sequence[SkillSource] | None = None) -> None:
        self.sources = default_skill_sources() if sources is None else tuple(sources)
        self._last_warnings: tuple[str, ...] = ()

    @property
    def warnings(self) -> tuple[str, ...]:
        return self._last_warnings

    def list(self, workspace: Path) -> list[SkillRef]:
        catalogue = self.catalogue(workspace)
        return list(catalogue.skills)

    def catalogue(self, workspace: Path) -> SkillCatalogue:
        refs: list[SkillRef] = []
        warnings: list[str] = []
        for source in self.sources:
            try:
                refs.extend(source.list_skills(workspace))
            except Exception as exc:
                warnings.append(f"{getattr(source, 'name', type(source).__name__)} failed: {exc}")
        by_name: dict[str, list[SkillRef]] = defaultdict(list)
        for ref in refs:
            by_name[ref.name].append(ref)

        winners: list[SkillRef] = []
        for name in sorted(by_name):
            group = sorted(by_name[name], key=lambda ref: _source_priority(ref.source), reverse=True)
            winning_priority = _source_priority(group[0].source)
            same_priority = [ref for ref in group if _source_priority(ref.source) == winning_priority]
            if len(same_priority) > 1:
                sources = ", ".join(ref.source for ref in same_priority)
                warnings.append(f"duplicate skill {name!r} at same priority: {sources}")
            winners.append(group[0])
        self._last_warnings = tuple(warnings)
        return SkillCatalogue(skills=tuple(winners), warnings=tuple(warnings))

    def load(self, skill_id_or_name: str, workspace: Path) -> LoadedSkill:
        refs = self.catalogue(workspace).skills
        wanted = skill_id_or_name.strip()
        for ref in refs:
            if wanted in {ref.id, ref.name}:
                return self._load_ref(ref, workspace)
        raise KeyError(f"Unknown skill: {skill_id_or_name}")

    def _load_ref(self, ref: SkillRef, workspace: Path) -> LoadedSkill:
        for source in self.sources:
            try:
                return source.load_skill(ref.id, workspace)
            except KeyError:
                continue
        raise KeyError(ref.id)


def _source_priority(source: str) -> int:
    if source == "project":
        return 100
    if source.startswith("package"):
        return 80
    if source == "user":
        return 50
    if source == "system":
        return 10
    return 0
