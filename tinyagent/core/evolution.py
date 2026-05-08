"""Out-of-tree self-evolution experiment scaffolding."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from tinyagent.core.skills import SkillRegistry

EVOLUTION_DIR = Path(".tinyagent") / "evolution"


@dataclass(frozen=True)
class EvolutionExperiment:
    experiment_id: str
    path: Path
    target_kind: str
    target_id: str
    candidate_path: Path
    report_path: Path


def create_skill_experiment(*, workspace: Path, skill_id: str, suite_path: Path) -> EvolutionExperiment:
    registry = SkillRegistry()
    loaded = registry.load(skill_id, workspace)
    experiment = _new_experiment(workspace, target_kind="skill", target_id=loaded.ref.name, suite_path=suite_path)
    candidate_dir = experiment.path / "candidates" / "candidate-1"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "SKILL.md").write_text(loaded.markdown)
    _write_spec(experiment, suite_path=suite_path, source_path=loaded.ref.path)
    _write_report(experiment, "Skill candidate copied for external editing. Run eval compare before accepting.")
    return experiment


def create_prompt_experiment(*, workspace: Path, prompt_id: str, suite_path: Path) -> EvolutionExperiment:
    experiment = _new_experiment(workspace, target_kind="prompt", target_id=prompt_id, suite_path=suite_path)
    candidate_dir = experiment.path / "candidates" / "candidate-1"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / f"{_safe_slug(prompt_id)}.md").write_text(
        f"# Prompt Candidate: {prompt_id}\n\nEdit this file out of tree, then run eval comparison before accepting.\n"
    )
    _write_spec(experiment, suite_path=suite_path, source_path="")
    _write_report(experiment, "Prompt candidate scaffolded for external editing. Core prompt auto-rewrite is disabled.")
    return experiment


def render_experiment_report(*, workspace: Path, experiment_id: str) -> str:
    path = _experiment_path(workspace, experiment_id)
    report = path / "reports" / "report.md"
    if not report.exists():
        raise FileNotFoundError(f"Missing evolution report: {experiment_id}")
    return report.read_text()


def accept_candidate(*, workspace: Path, candidate_id: str) -> Path:
    experiment_id, candidate_name = _split_candidate_id(candidate_id)
    experiment_path = _experiment_path(workspace, experiment_id)
    spec = json.loads((experiment_path / "experiment.json").read_text())
    candidate_dir = experiment_path / "candidates" / candidate_name
    if not candidate_dir.is_dir():
        raise FileNotFoundError(f"Unknown candidate: {candidate_id}")
    accepted = experiment_path / "accepted" / candidate_name
    accepted.parent.mkdir(parents=True, exist_ok=True)
    if accepted.exists():
        raise FileExistsError(f"Candidate already accepted: {candidate_id}")
    shutil.copytree(candidate_dir, accepted)
    if spec.get("target_kind") == "skill":
        skill_name = _safe_slug(str(spec.get("target_id") or candidate_name))
        target = (workspace.expanduser().resolve() / ".tinyagent" / "skills" / skill_name).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"Skill already exists: {target}")
        shutil.copytree(candidate_dir, target)
        return target
    return accepted


def _new_experiment(workspace: Path, *, target_kind: str, target_id: str, suite_path: Path) -> EvolutionExperiment:
    root = workspace.expanduser().resolve() / EVOLUTION_DIR / "experiments"
    root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    experiment_id = f"evo-{target_kind}-{_safe_slug(target_id)}-{timestamp}"
    path = root / experiment_id
    index = 2
    while path.exists():
        path = root / f"{experiment_id}-{index}"
        index += 1
    path.mkdir()
    return EvolutionExperiment(
        experiment_id=path.name,
        path=path,
        target_kind=target_kind,
        target_id=target_id,
        candidate_path=path / "candidates" / "candidate-1",
        report_path=path / "reports" / "report.md",
    )


def _write_spec(experiment: EvolutionExperiment, *, suite_path: Path, source_path: str) -> None:
    spec = {
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "experiment_id": experiment.experiment_id,
        "target_kind": experiment.target_kind,
        "target_id": experiment.target_id,
        "suite_path": str(suite_path.expanduser()),
        "source_path": source_path,
        "candidate_id": f"{experiment.experiment_id}/candidate-1",
        "auto_install": False,
        "core_code_evolution": False,
    }
    (experiment.path / "experiment.json").write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n")


def _write_report(experiment: EvolutionExperiment, note: str) -> None:
    report = experiment.path / "reports" / "report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        "# Evolution Report\n\n"
        f"- experiment: `{experiment.experiment_id}`\n"
        f"- target: `{experiment.target_kind}:{experiment.target_id}`\n"
        f"- candidate: `{experiment.experiment_id}/candidate-1`\n"
        "- status: `draft`\n\n"
        f"{note}\n\n"
        "Acceptance requires a human review plus an eval comparison report.\n"
    )


def _experiment_path(workspace: Path, experiment_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", experiment_id):
        raise ValueError(f"Invalid experiment id: {experiment_id}")
    root = workspace.expanduser().resolve() / EVOLUTION_DIR / "experiments"
    path = (root / experiment_id).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Unsafe experiment id: {experiment_id}") from exc
    if not path.is_dir():
        raise FileNotFoundError(f"Unknown evolution experiment: {experiment_id}")
    return path


def _split_candidate_id(candidate_id: str) -> tuple[str, str]:
    parts = candidate_id.strip().split("/", 1)
    if len(parts) != 2:
        raise ValueError("Candidate id must look like <experiment-id>/candidate-1")
    experiment_id, candidate_name = parts
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", candidate_name):
        raise ValueError(f"Invalid candidate id: {candidate_id}")
    return experiment_id, candidate_name


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower()).strip("-._")
    return slug or "candidate"
