"""First-class skill discovery and loading."""

from tinyagent.core.skills.discovery import DirectorySkillSource, default_skill_sources
from tinyagent.core.skills.parser import parse_skill_markdown
from tinyagent.core.skills.registry import SkillRegistry
from tinyagent.core.skills.types import LoadedSkill, SkillRef, SkillSource

__all__ = [
    "DirectorySkillSource",
    "LoadedSkill",
    "SkillRef",
    "SkillRegistry",
    "SkillSource",
    "default_skill_sources",
    "parse_skill_markdown",
]
