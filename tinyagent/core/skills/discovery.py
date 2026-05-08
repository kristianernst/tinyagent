"""Skill source discovery."""

from __future__ import annotations

from pathlib import Path

from tinyagent.core.skills.parser import parse_skill_file
from tinyagent.core.skills.types import LoadedSkill, SkillRef


class DirectorySkillSource:
    def __init__(self, root: Path, *, name: str, source: str | None = None, trust: str = "untrusted") -> None:
        self.root = root.expanduser()
        self.name = name
        self.source = source or name
        self.trust = trust

    def list_skills(self, workspace: Path) -> tuple[SkillRef, ...]:
        root = self._root(workspace)
        if not root.exists() or not root.is_dir():
            return ()
        refs: list[SkillRef] = []
        for child in sorted(root.iterdir(), key=lambda path: path.name):
            skill_path = _safe_skill_path(root, child)
            if skill_path is None:
                continue
            refs.append(self._ref_from_path(skill_path))
        return tuple(refs)

    def load_skill(self, skill_id: str, workspace: Path) -> LoadedSkill:
        for ref in self.list_skills(workspace):
            if skill_id in {ref.id, ref.name}:
                skill_path = Path(ref.path)
                parsed = parse_skill_file(skill_path, fallback_name=skill_path.parent.name)
                files = _skill_files(skill_path.parent)
                return LoadedSkill(
                    ref=ref,
                    markdown=parsed.markdown,
                    files=files,
                    truncated=parsed.truncated,
                    token_estimate=parsed.token_estimate,
                    warnings=parsed.warnings,
                )
        raise KeyError(skill_id)

    def _root(self, workspace: Path) -> Path:
        if self.root.is_absolute():
            return self.root.resolve()
        return (workspace / self.root).resolve()

    def _ref_from_path(self, skill_path: Path) -> SkillRef:
        parsed = parse_skill_file(skill_path, fallback_name=skill_path.parent.name)
        return SkillRef(
            id=_skill_id(self.source, parsed.name),
            name=parsed.name,
            description=parsed.description,
            source=self.source,
            path=str(skill_path.resolve()),
            tags=parsed.tags,
            trust=self.trust,
            warnings=parsed.warnings,
        )


def default_skill_sources() -> tuple[DirectorySkillSource, ...]:
    return (
        DirectorySkillSource(Path(".tinyagent/skills"), name="project", trust="untrusted"),
        DirectorySkillSource(Path(".agent/skills"), name="project-alt", source="project", trust="untrusted"),
        DirectorySkillSource(Path.home() / ".tinyagent" / "skills", name="user", trust="untrusted"),
    )


def _skill_files(root: Path) -> tuple[str, ...]:
    resolved_root = root.resolve()
    files: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            path.resolve().relative_to(resolved_root)
        except ValueError:
            continue
        files.append(path.relative_to(root).as_posix())
    return tuple(files)


def _skill_id(source: str, name: str) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in f"{source}_{name}")
    return f"skill_{safe.strip('_')}"


def _safe_skill_path(root: Path, child: Path) -> Path | None:
    if not child.is_dir():
        return None
    skill_path = child / "SKILL.md"
    if not skill_path.is_file():
        return None
    resolved_root = root.resolve()
    resolved_child = child.resolve()
    resolved_skill = skill_path.resolve()
    try:
        resolved_child.relative_to(resolved_root)
        resolved_skill.relative_to(resolved_child)
    except ValueError:
        return None
    return resolved_skill
