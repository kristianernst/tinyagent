"""Reviewable skill drafts generated from successful run traces."""

from __future__ import annotations

import importlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from tinyagent.core.events import load_events_jsonl
from tinyagent.core.skills.parser import parse_skill_file
from tinyagent.core.skills.types import LoadedSkill, SkillRef
from tinyagent.runtime.run_record import RunRecord, load_run_record

SKILL_DRAFTS_DIR = Path(".tinyagent") / "skill-drafts"
PROJECT_SKILLS_DIR = Path(".tinyagent") / "skills"
REJECTED_DIR = SKILL_DRAFTS_DIR / "rejected"


@dataclass(frozen=True)
class SkillDraft:
    draft_id: str
    name: str
    path: Path
    status: str
    source_run_id: str
    created_at: str


def draft_from_run(run_path: Path, *, workspace: Path, drafts_dir: Path | None = None, debug_artifacts: bool = False) -> SkillDraft:
    record = load_run_record(run_path)
    if record.status != "completed":
        raise ValueError(f"Cannot draft a skill from non-completed run: {record.status}")
    root = (workspace.expanduser().resolve() / (drafts_dir or SKILL_DRAFTS_DIR)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    draft_id = _unique_draft_id(root, record)
    draft_dir = root / draft_id
    draft_dir.mkdir()
    skill_name = _skill_name(record)
    source = _source_summary(record, run_path, draft_id=draft_id, skill_name=skill_name, debug_artifacts=debug_artifacts)
    (draft_dir / "SKILL.md").write_text(_render_skill_markdown(record, skill_name, source))
    (draft_dir / "source-run.json").write_text(json.dumps(source, indent=2, sort_keys=True) + "\n")
    (draft_dir / "status.json").write_text(json.dumps(_draft_status(draft_id, skill_name, record), indent=2, sort_keys=True) + "\n")
    (draft_dir / "eval-plan.md").write_text(_render_eval_plan(record, skill_name))
    return SkillDraft(
        draft_id=draft_id,
        name=skill_name,
        path=draft_dir,
        status="draft",
        source_run_id=record.run_id,
        created_at=str(source["created_at"]),
    )


def list_drafts(*, workspace: Path, drafts_dir: Path | None = None) -> list[SkillDraft]:
    root = (workspace.expanduser().resolve() / (drafts_dir or SKILL_DRAFTS_DIR)).resolve()
    if not root.exists():
        return []
    drafts: list[SkillDraft] = []
    for child in sorted(root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name == "rejected":
            continue
        record = _read_source_record(child)
        source_run = record.get("source_run") if isinstance(record.get("source_run"), dict) else {}
        drafts.append(
            SkillDraft(
                draft_id=child.name,
                name=str(record.get("skill_name") or child.name),
                path=child,
                status=str(record.get("status") or "draft"),
                source_run_id=str(source_run.get("run_id") or ""),
                created_at=str(record.get("created_at") or ""),
            )
        )
    return drafts


def show_draft(draft_id: str, *, workspace: Path, drafts_dir: Path | None = None) -> str:
    draft_dir = _draft_dir(draft_id, workspace=workspace, drafts_dir=drafts_dir)
    return (draft_dir / "SKILL.md").read_text()


def install_draft(
    draft_id: str,
    *,
    workspace: Path,
    skill_root: Path | None = None,
    drafts_dir: Path | None = None,
    replace: bool = False,
) -> Path:
    draft_dir = _draft_dir(draft_id, workspace=workspace, drafts_dir=drafts_dir)
    record = _read_source_record(draft_dir)
    skill_name = _safe_slug(str(record.get("skill_name") or draft_id))
    parse_skill_file(draft_dir / "SKILL.md", fallback_name=skill_name)
    root = (workspace.expanduser().resolve() / (skill_root or PROJECT_SKILLS_DIR)).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / skill_name).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Unsafe skill draft install target: {skill_name}") from exc
    if target.exists() and not replace:
        raise FileExistsError(f"Skill already exists: {target}")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir()
    shutil.copy2(draft_dir / "SKILL.md", target / "SKILL.md")
    return target


def eval_draft(
    draft_id: str,
    *,
    workspace: Path,
    suite_path: Path,
    output_dir: Path,
    model_factory,
    profile,
    tools,
    policy,
):
    draft_dir = _draft_dir(draft_id, workspace=workspace, drafts_dir=None)
    baseline_dir = output_dir / "baseline"
    draft_run_dir = output_dir / "draft"
    eval_runner = importlib.import_module("tinyagent.evals.runner")

    baseline = eval_runner.run_eval_suite(
        suite_path,
        output_dir=baseline_dir,
        model_factory=model_factory,
        profile=profile,
        tools=tools,
        policy=policy,
        variant_name="baseline",
    )
    from tinyagent.core.resources import LoadedResources

    draft = eval_runner.run_eval_suite(
        suite_path,
        output_dir=draft_run_dir,
        model_factory=model_factory,
        profile=profile,
        tools=tools,
        policy=policy,
        variant_name="draft",
        resources=LoadedResources(skill_sources=(_SingleDraftSkillSource(draft_dir),)),
    )
    comparison = eval_runner.EvalComparison(suite_path=suite_path, output_dir=output_dir, variants=[baseline, draft])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "comparison.md").write_text(eval_runner.render_eval_comparison(comparison))
    (output_dir / "comparison.json").write_text(
        json.dumps(
            {
                "suite_path": str(suite_path),
                "output_dir": str(output_dir),
                "variants": [
                    {"name": run.variant_name, "results": [result.to_json_dict() for result in run.results]} for run in comparison.variants
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return comparison


def reject_draft(draft_id: str, *, workspace: Path, drafts_dir: Path | None = None) -> Path:
    draft_dir = _draft_dir(draft_id, workspace=workspace, drafts_dir=drafts_dir)
    rejected_root = (workspace.expanduser().resolve() / (drafts_dir or SKILL_DRAFTS_DIR) / "rejected").resolve()
    rejected_root.mkdir(parents=True, exist_ok=True)
    target = rejected_root / draft_dir.name
    if target.exists():
        target = rejected_root / f"{draft_dir.name}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    shutil.move(str(draft_dir), str(target))
    return target


class _SingleDraftSkillSource:
    name = "draft"
    source = "draft"
    trust = "untrusted"

    def __init__(self, draft_dir: Path) -> None:
        self.draft_dir = draft_dir.resolve()

    def list_skills(self, workspace: Path) -> tuple[SkillRef, ...]:
        skill_path = self.draft_dir / "SKILL.md"
        if not skill_path.is_file():
            return ()
        parsed = parse_skill_file(skill_path, fallback_name=self.draft_dir.name)
        return (
            SkillRef(
                id=_skill_id(self.source, parsed.name),
                name=parsed.name,
                description=parsed.description,
                source=self.source,
                path=str(skill_path),
                tags=parsed.tags,
                trust=self.trust,
                warnings=parsed.warnings,
            ),
        )

    def load_skill(self, skill_id: str, workspace: Path) -> LoadedSkill:
        refs = self.list_skills(workspace)
        if not refs or skill_id not in {refs[0].id, refs[0].name}:
            raise KeyError(skill_id)
        skill_path = Path(refs[0].path)
        parsed = parse_skill_file(skill_path, fallback_name=skill_path.parent.name)
        return LoadedSkill(
            ref=refs[0],
            markdown=parsed.markdown,
            files=("SKILL.md",),
            truncated=parsed.truncated,
            token_estimate=parsed.token_estimate,
            warnings=parsed.warnings,
        )


def _source_summary(
    record: RunRecord,
    run_path: Path,
    *,
    draft_id: str,
    skill_name: str,
    debug_artifacts: bool,
) -> dict[str, Any]:
    root = run_path.expanduser().resolve()
    if root.name == "events.jsonl":
        root = root.parent
    events = load_events_jsonl(root / "events.jsonl")
    commands = [command.cmd for command in record.commands if command.cmd]
    verification_commands = [cmd for cmd in commands if _looks_like_verification(cmd)]
    hidden_artifacts = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "artifacts").glob("*")
        if path.name.startswith(("model-request", "model-response"))
    )
    summary: dict[str, Any] = {
        "version": 1,
        "draft_id": draft_id,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "draft",
        "skill_name": skill_name,
        "source_run": {
            "run_id": record.run_id,
            "run_path": _redact_path(str(root)),
            "status": record.status,
            "task": _sanitize_text(record.task),
        },
        "inputs": {
            "final_output_tokens": record.final_output_tokens,
            "final_diff_sha256": _sha256_file(root / "final.diff"),
            "event_count": len(events),
            "hidden_artifacts_skipped": hidden_artifacts,
        },
        "changed_paths": _changed_files(root / "final.diff"),
        "verification": [
            {"cmd": _sanitize_text(cmd), "returncode": _command_returncode(record, cmd)} for cmd in verification_commands[:10]
        ],
        "metrics": {
            "duration_seconds": record.duration_seconds,
            "turn_count": record.turn_count,
            "model_call_count": record.model_call_count,
            "tool_call_count": record.tool_call_count,
            "final_diff_tokens": record.final_diff_tokens,
        },
        "tools": sorted({call.tool for call in record.tool_calls if call.tool}),
        "commands": [_sanitize_text(command) for command in commands[:20]],
        "included_debug_artifacts": bool(debug_artifacts),
    }
    if debug_artifacts:
        summary["debug_artifacts"] = {
            "final_output_path": record.final_output_path,
            "final_diff_path": record.final_diff_path,
        }
    return summary


def _render_skill_markdown(record: RunRecord, skill_name: str, source: dict[str, Any]) -> str:
    commands = source.get("commands") if isinstance(source.get("commands"), list) else []
    verification_data = source.get("verification") if isinstance(source.get("verification"), list) else []
    verification = [str(item.get("cmd")) for item in verification_data if isinstance(item, dict) and item.get("cmd")]
    changed = source.get("changed_paths") if isinstance(source.get("changed_paths"), list) else []
    command_lines = "\n".join(f"- `{cmd}`" for cmd in commands[:8]) or "- No reusable shell commands identified."
    verification_lines = "\n".join(f"- `{cmd}`" for cmd in verification[:5]) or "- Re-run the project-specific validation used by the task."
    changed_lines = "\n".join(f"- `{path}`" for path in changed[:12]) or "- No changed files recorded."
    return (
        "---\n"
        f"name: {skill_name}\n"
        f"description: Reusable procedure drafted from run {record.run_id}.\n"
        "tags: [draft, learned]\n"
        "---\n\n"
        "# Skill\n\n"
        "## When to use\n\n"
        f"Use when a task resembles: {record.task or 'the source run task'}\n\n"
        "## Procedure\n\n"
        "- Inspect the relevant files and current repository state before editing.\n"
        "- Reuse only the parts of this draft that match the current task.\n"
        "- Keep workspace changes small and verify after mutation.\n\n"
        "## Commands\n\n"
        f"{command_lines}\n\n"
        "## Verification\n\n"
        f"{verification_lines}\n\n"
        "## Failure modes\n\n"
        "- Source trace may be overfit to one repository state.\n"
        "- Commands may require adaptation before reuse.\n"
        "- Do not claim verification unless the current run actually executed it.\n\n"
        "## Changed Files In Source Trace\n\n"
        f"{changed_lines}\n\n"
        "## Source trace\n\n"
        f"- run_id: `{record.run_id}`\n"
        f"- status: `{record.status}`\n"
        f"- final_diff_tokens: `{record.final_diff_tokens}`\n"
    )


def _render_eval_plan(record: RunRecord, skill_name: str) -> str:
    return (
        "# Eval Plan\n\n"
        f"- Draft: `{skill_name}`\n"
        f"- Source run: `{record.run_id}`\n"
        "- Install into a temporary skill source or compare a draft-enabled variant.\n"
        "- Run the smallest eval case that reproduces the original workflow.\n"
        "- Accept only if the draft improves or preserves solve rate and does not add policy/invariant failures.\n"
    )


def _read_source_record(draft_dir: Path) -> dict[str, Any]:
    path = draft_dir / "source-run.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _draft_status(draft_id: str, skill_name: str, record: RunRecord) -> dict[str, object]:
    return {
        "version": 1,
        "draft_id": draft_id,
        "skill_name": skill_name,
        "status": "draft",
        "source_run_id": record.run_id,
        "auto_installed": False,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _draft_dir(draft_id: str, *, workspace: Path, drafts_dir: Path | None) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", draft_id):
        raise ValueError(f"Invalid draft id: {draft_id}")
    root = (workspace.expanduser().resolve() / (drafts_dir or SKILL_DRAFTS_DIR)).resolve()
    path = (root / draft_id).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Unsafe draft id: {draft_id}") from exc
    if not path.is_dir():
        raise FileNotFoundError(f"Unknown skill draft: {draft_id}")
    return path


def _unique_draft_id(root: Path, record: RunRecord) -> str:
    base = _safe_slug(record.run_id or record.task or "run")
    candidate = f"draft-{base}"
    index = 2
    while (root / candidate).exists():
        candidate = f"draft-{base}-{index}"
        index += 1
    return candidate


def _skill_name(record: RunRecord) -> str:
    source = record.task or record.run_id or "learned-skill"
    return f"learned-{_safe_slug(source)[:48].strip('-') or 'skill'}"


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower()).strip("-._")
    return slug or "skill"


def _skill_id(source: str, name: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in f"{source}_{name}")
    return f"skill_{safe.strip('_')}"


def _looks_like_verification(command: str) -> bool:
    text = command.lower()
    return any(token in text for token in ("pytest", "npm test", "uv run pytest", "cargo test", "go test", "python -m pytest"))


def _command_returncode(record: RunRecord, command: str) -> int | None:
    for item in record.commands:
        if item.cmd == command:
            return item.returncode
    return None


def _sha256_file(path: Path) -> str:
    if not path.exists():
        return ""
    return sha256(path.read_bytes()).hexdigest()


SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)\S+")


def _sanitize_text(value: str) -> str:
    return SECRET_PATTERN.sub(r"\1\2[redacted]", _redact_path(value))


def _redact_path(value: str) -> str:
    return re.sub(r"/[^\s`'\"]*\.tinyagent/runs/[^\s`'\"]+", "[run-output]", value)


def _changed_files(diff_path: Path) -> list[str]:
    if not diff_path.exists():
        return []
    files: list[str] = []
    for line in diff_path.read_text(errors="replace").splitlines():
        if not line.startswith("diff --git "):
            continue
        parts = line.split()
        if len(parts) >= 4:
            files.append(parts[3].removeprefix("b/"))
    return sorted(set(files))
