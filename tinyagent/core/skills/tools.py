"""Model-visible skill tools."""

from __future__ import annotations

from tinyagent.core.contracts import ToolRuntime
from tinyagent.core.output import write_text_artifact
from tinyagent.core.path_safety import safe_artifact_name
from tinyagent.core.skills.registry import SkillRegistry
from tinyagent.core.state import RunState, ToolCall, ToolResult
from tinyagent.core.token_utils import clip_text_to_token_budget, estimate_tokens, fits_token_budget
from tinyagent.core.tools.core import error_result, visible_output

MAX_LOADED_SKILL_TOKENS = 15_000


class ListSkillsTool:
    name = "list_skills"
    runtime = ToolRuntime(parallel_safe=True, lock_key="skills")
    schema = {
        "name": "list_skills",
        "description": "List available skills by name, description, source, and tags. Use load_skill to read full instructions.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
        },
    }

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or SkillRegistry()

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        try:
            query = str(call.args.get("query") or "").strip().lower()
            tags = {str(tag).strip().lower() for tag in call.args.get("tags") or () if str(tag).strip()}
            limit = min(max(int(call.args.get("limit", 20)), 1), 50)
            catalogue = self.registry.catalogue(state.workspace.root)
            skills = [_matches(ref, query=query, tags=tags) for ref in catalogue.skills]
            matched = [ref for ref in skills if ref is not None]
            visible = matched[:limit]
        except Exception as exc:
            return error_result(self.name, call, exc)

        lines = ["Available skills:"]
        if not visible:
            lines.append("No skills found.")
        for ref in visible:
            tag_text = ", ".join(ref.tags) if ref.tags else "none"
            lines.extend(
                [
                    "",
                    f"- {ref.name} [{ref.source}]",
                    f"  id: {ref.id}",
                    f"  description: {ref.description}",
                    f"  tags: {tag_text}",
                    f"  load: load_skill({{\"name_or_id\":\"{ref.name}\"}})",
                ]
            )
            if ref.warnings:
                lines.append(f"  warnings: {'; '.join(ref.warnings)}")
        if len(matched) > len(visible):
            lines.append(f"\n[truncated: {len(matched) - len(visible)} more skill(s)]")
        if catalogue.warnings:
            lines.append("\nWarnings:")
            lines.extend(f"- {warning}" for warning in catalogue.warnings)
        output = "\n".join(lines)
        output_tokens = estimate_tokens(output)
        state.emit(
            "skill.listed",
            {
                "count": len(visible),
                "matched_count": len(matched),
                "truncated": len(matched) > len(visible),
                "warnings": list(catalogue.warnings),
            },
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(output, state),
            data={
                "count": len(visible),
                "matched_count": len(matched),
                "truncated": len(matched) > len(visible),
                "warnings": list(catalogue.warnings),
                "output_tokens": output_tokens,
            },
            truncated=not fits_token_budget(output, state.budgets.max_tool_output_tokens_visible),
        )


class LoadSkillTool:
    name = "load_skill"
    runtime = ToolRuntime(parallel_safe=True, lock_key="skills")
    schema = {
        "name": "load_skill",
        "description": "Load full instructions for one skill. Does not execute scripts; scripts must be run through shell under policy.",
        "parameters": {
            "type": "object",
            "properties": {
                "name_or_id": {"type": "string"},
            },
            "required": ["name_or_id"],
        },
    }

    def __init__(self, registry: SkillRegistry | None = None) -> None:
        self.registry = registry or SkillRegistry()

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        name_or_id = str(call.args.get("name_or_id") or "").strip()
        if not name_or_id:
            return ToolResult(tool_name=self.name, call_id=call.id, output="name_or_id is required", ok=False)
        try:
            loaded = self.registry.load(name_or_id, state.workspace.root)
        except Exception as exc:
            state.emit("skill.load.failed", {"name_or_id": name_or_id, "reason": str(exc)})
            return error_result(self.name, call, exc)

        markdown = loaded.markdown
        truncated = loaded.truncated or not fits_token_budget(markdown, MAX_LOADED_SKILL_TOKENS)
        if not fits_token_budget(markdown, MAX_LOADED_SKILL_TOKENS):
            markdown = clip_text_to_token_budget(markdown, MAX_LOADED_SKILL_TOKENS)
        files = [path for path in loaded.files if path != "SKILL.md"]
        lines = [
            f"Skill: {loaded.ref.name}",
            f"Source: {loaded.ref.source}",
            f"Path: {loaded.ref.path}",
            "",
            "<skill_instructions>",
            markdown,
            "</skill_instructions>",
            "",
            "Files:",
        ]
        lines.extend(f"- {path}" for path in files)
        if not files:
            lines.append("- none")
        warnings = list(dict.fromkeys((*loaded.ref.warnings, *loaded.warnings)))
        if warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in warnings)
        output = "\n".join(lines)
        output_tokens = estimate_tokens(output)
        artifact = write_text_artifact(
            state,
            f"skill-{safe_artifact_name(call.id)}.md",
            output,
            kind="skill_loaded",
        )
        state.emit(
            "skill.loaded",
            {
                "skill_id": loaded.ref.id,
                "name": loaded.ref.name,
                "source": loaded.ref.source,
                "path": loaded.ref.path,
                "instruction_tokens": estimate_tokens(loaded.markdown),
                "files": list(files),
                "truncated": truncated,
                "output_artifact": artifact,
                "output_tokens": output_tokens,
            },
            artifact_refs=[artifact],
        )
        return ToolResult(
            tool_name=self.name,
            call_id=call.id,
            output=visible_output(output, state),
            artifact_path=artifact,
            data={
                "skill_id": loaded.ref.id,
                "name": loaded.ref.name,
                "source": loaded.ref.source,
                "path": loaded.ref.path,
                "instruction_tokens": estimate_tokens(loaded.markdown),
                "files": list(files),
                "truncated": truncated,
                "output_artifact": artifact,
                "output_tokens": output_tokens,
            },
            truncated=truncated or not fits_token_budget(output, state.budgets.max_tool_output_tokens_visible),
            summary=f"Loaded skill {loaded.ref.name}.",
            content_preview=clip_text_to_token_budget(output, 500),
        )


def _matches(ref, *, query: str, tags: set[str]):
    if query and query not in ref.name.lower() and query not in ref.description.lower():
        return None
    if tags and tags.isdisjoint({tag.lower() for tag in ref.tags}):
        return None
    return ref
