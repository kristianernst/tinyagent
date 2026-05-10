from __future__ import annotations

import os

import pytest

from tinyagent.core.contracts import ProfileRuntimeCapabilities
from tinyagent.core.extensions import ExtensionHost, ExtensionInfo
from tinyagent.core.policy import LocalPolicy, PolicyConfig, PolicyRule
from tinyagent.core.profile_catalog import DEFAULT_RUNTIME_CAPABILITIES, TINY_PI_RUNTIME_CAPABILITIES
from tinyagent.core.resources import ResourceLoader, ResourceLoaderConfig
from tinyagent.core.skills import DirectorySkillSource, SkillRegistry
from tinyagent.core.skills.parser import MAX_SKILL_MARKDOWN_BYTES, parse_skill_markdown
from tinyagent.core.skills.tools import ListSkillsTool, LoadSkillTool
from tinyagent.core.state import RunState, ToolCall, Workspace


def _write_skill(root, name: str, markdown: str, *, script: bool = False):
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(markdown)
    if script:
        scripts = skill_dir / "scripts"
        scripts.mkdir()
        (scripts / "run.py").write_text("print('ok')\n")
    return skill_dir


def test_skill_parser_accepts_frontmatter_and_derives_missing_fields() -> None:
    parsed = parse_skill_markdown(
        "---\nname: repo-review\ndescription: Review diffs.\ntags: [review, git]\n---\n# Review\nBody\n",
        fallback_name="fallback",
    )
    missing = parse_skill_markdown("Use this when reviewing changes.\n\nMore detail.\n", fallback_name="folder-name")

    assert parsed.name == "repo-review"
    assert parsed.description == "Review diffs."
    assert parsed.tags == ("review", "git")
    assert missing.name == "folder-name"
    assert missing.description == "Use this when reviewing changes."
    assert "missing frontmatter" in missing.warnings


def test_skill_discovery_deduplicates_project_over_user_and_lists_warnings(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    project_root = tmp_path / "repo"
    project_root.mkdir()
    _write_skill(
        project_root / ".tinyagent" / "skills",
        "review",
        "---\nname: review\ndescription: Project review.\ntags: [project]\n---\nProject\n",
    )
    _write_skill(
        home / ".tinyagent" / "skills",
        "review",
        "---\nname: review\ndescription: User review.\ntags: [user]\n---\nUser\n",
    )
    registry = SkillRegistry()

    skills = registry.list(project_root)

    assert [(skill.name, skill.source, skill.description) for skill in skills] == [("review", "project", "Project review.")]


def test_skill_registry_explicit_empty_sources_disables_discovery(tmp_path) -> None:
    _write_skill(
        tmp_path / ".tinyagent" / "skills",
        "review",
        "---\nname: review\ndescription: Project review.\n---\nProject\n",
    )

    assert SkillRegistry(()).list(tmp_path) == []
    assert SkillRegistry().list(tmp_path)


def test_resource_loader_no_discovery_and_tiny_pi_load_no_skill_sources(tmp_path) -> None:
    assert (
        ResourceLoader(ResourceLoaderConfig(no_discovery=True))
        .load(tmp_path, runtime_capabilities=DEFAULT_RUNTIME_CAPABILITIES)
        .skill_sources
        == ()
    )
    assert ResourceLoader().load(tmp_path, runtime_capabilities=TINY_PI_RUNTIME_CAPABILITIES).skill_sources == ()
    assert ResourceLoader().load(tmp_path, runtime_capabilities=DEFAULT_RUNTIME_CAPABILITIES).skill_sources


def test_resource_loader_can_use_resolved_runtime_capabilities(tmp_path) -> None:
    extension_path = tmp_path / "extension.py"
    extension_path.write_text("raise RuntimeError('should not load')\n")

    resources = ResourceLoader(
        ResourceLoaderConfig(memory_enabled=True, trust="trusted", extension_paths=(extension_path,))
    ).load(
        tmp_path,
        runtime_capabilities=ProfileRuntimeCapabilities(skills=False, dynamic_context=False, extensions=False),
    )

    assert resources.skill_sources == ()
    assert resources.context_sources == ()
    assert resources.extensions == ()


def test_resource_loader_skips_extension_loading_for_tiny_pi(tmp_path) -> None:
    extension_path = tmp_path / "extension.py"
    extension_path.write_text("raise RuntimeError('should not load')\n")

    resources = ResourceLoader(ResourceLoaderConfig(trust="trusted", extension_paths=(extension_path,))).load(
        tmp_path,
        runtime_capabilities=TINY_PI_RUNTIME_CAPABILITIES,
    )

    assert resources.extensions == ()


def test_resource_loader_extension_paths_require_trust_or_explicit_allowance(tmp_path) -> None:
    extension_path = tmp_path / "extension.py"
    extension_path.write_text("raise RuntimeError('should not import untrusted extension')\n")

    with pytest.raises(PermissionError, match="trusted workspace or explicit extension allowance"):
        ResourceLoader(ResourceLoaderConfig(extension_paths=(extension_path,))).load(
            tmp_path,
            runtime_capabilities=DEFAULT_RUNTIME_CAPABILITIES,
        )

    extension_path.write_text("class Extension:\n    name = 'local-ext'\n\nextension = Extension()\n")
    trusted = ResourceLoader(ResourceLoaderConfig(trust="trusted", extension_paths=(extension_path,))).load(
        tmp_path,
        runtime_capabilities=DEFAULT_RUNTIME_CAPABILITIES,
    )
    allowed = ResourceLoader(
        ResourceLoaderConfig(extension_paths=(extension_path,), allow_extension_paths=True)
    ).load(tmp_path, runtime_capabilities=DEFAULT_RUNTIME_CAPABILITIES)

    assert [extension.name for extension in trusted.extensions] == ["local-ext"]
    assert [extension.name for extension in allowed.extensions] == ["local-ext"]


def test_extension_info_is_metadata_only() -> None:
    class DeclaredExtension:
        name = "declared"

        def info(self):
            return ExtensionInfo(name="declared", version="1.0", permissions=("network",))

    class BrokenInfoExtension:
        name = "broken"

        def info(self):
            raise RuntimeError("metadata failed")

    info = ExtensionHost([DeclaredExtension(), BrokenInfoExtension()]).info()

    assert info[0] == ExtensionInfo(name="declared", version="1.0", permissions=("network",))
    assert info[1].name == "broken"
    assert "metadata failed" in info[1].description


def test_list_and_load_skill_tools_emit_events_and_list_scripts_without_execution(tmp_path) -> None:
    _write_skill(
        tmp_path / ".tinyagent" / "skills",
        "repo-review",
        "---\nname: repo-review\ndescription: Review repository changes.\ntags:\n  - review\n---\n# Repo review\nUse git diff.\n",
        script=True,
    )
    state = RunState.create("skills", Workspace(tmp_path), run_id="run_skills")

    listed = ListSkillsTool().run(ToolCall(name="list_skills", args={"query": "repo", "limit": 10}), state)
    loaded = LoadSkillTool().run(ToolCall(name="load_skill", args={"name_or_id": "repo-review"}), state)

    assert listed.ok is True
    assert "repo-review [project]" in listed.output
    assert listed.data["count"] == 1
    assert loaded.ok is True
    assert loaded.artifact_path
    assert (state.output_dir / loaded.artifact_path).exists()
    assert "<skill_instructions>" in loaded.output
    assert "- scripts/run.py" in loaded.output
    assert "print('ok')" not in loaded.output
    assert [event.type for event in state.events if event.type.startswith("skill.")] == ["skill.listed", "skill.loaded"]


def test_load_skill_caps_large_skill_content(tmp_path) -> None:
    _write_skill(
        tmp_path / ".tinyagent" / "skills",
        "large",
        "---\nname: large\ndescription: Large skill.\n---\n" + ("x" * (MAX_SKILL_MARKDOWN_BYTES + 10)),
    )
    state = RunState.create("skills", Workspace(tmp_path), run_id="run_large_skill")

    loaded = LoadSkillTool().run(ToolCall(name="load_skill", args={"name_or_id": "large"}), state)

    assert loaded.ok is True
    assert loaded.data["truncated"] is True
    assert "truncated" in loaded.output


def test_skill_discovery_skips_symlink_escapes(tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    _write_skill(outside, "leak", "---\nname: leak\ndescription: Outside skill.\n---\nsecret\n")
    project_skills = tmp_path / ".tinyagent" / "skills"
    project_skills.mkdir(parents=True)
    try:
        os.symlink(outside / "leak", project_skills / "leak")
    except (AttributeError, OSError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    registry = SkillRegistry()

    assert registry.list(tmp_path) == []


def test_skill_policy_can_deny_loading(tmp_path) -> None:
    state = RunState.create("skills", Workspace(tmp_path), run_id="run_skill_policy")
    policy = LocalPolicy(config=PolicyConfig(default="allow", rules=(PolicyRule("skill", "*", "deny"),)))

    decision = policy.evaluate(ToolCall(name="load_skill", args={"name_or_id": "review"}), state)

    assert decision.kind == "deny"
    assert decision.permission == "skill"


def test_extensions_contribute_skill_sources(tmp_path) -> None:
    package_root = tmp_path / "package_skills"
    _write_skill(package_root, "qmd", "---\nname: qmd/search\ndescription: Search with QMD.\n---\nUse qmd.\n")

    class PackageExtension:
        name = "package"

        def skills(self):
            return [DirectorySkillSource(package_root, name="package:qmd", trust="untrusted")]

    host = ExtensionHost([PackageExtension()])
    registry = SkillRegistry(host.skills())

    skills = registry.list(tmp_path)

    assert [(skill.name, skill.source) for skill in skills] == [("qmd/search", "package:qmd")]


def test_context_search_uses_state_skill_registry_for_extension_sources(tmp_path) -> None:
    from tinyagent.core.context_sources import ContextRegistry, ContextSearchTool, default_context_sources

    package_root = tmp_path / "package_skills"
    _write_skill(package_root, "qmd", "---\nname: qmd/search\ndescription: Search with QMD.\n---\nUse qmd.\n")
    state = RunState.create("skills", Workspace(tmp_path), run_id="run_skill_context")
    state.skill_registry = SkillRegistry([DirectorySkillSource(package_root, name="package:qmd", trust="untrusted")])
    state.context_registry = ContextRegistry(default_context_sources(state.skill_registry))

    result = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "QMD", "source": "skills"}), state)

    assert result.ok is True
    assert "qmd/search" in result.output
