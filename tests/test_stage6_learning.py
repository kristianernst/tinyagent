from __future__ import annotations

import json
import sys
from pathlib import Path

from tinyagent.core.context_sources import ContextReadTool, ContextRegistry, ContextSearchTool, default_context_sources
from tinyagent.core.evolution import accept_candidate, create_skill_experiment
from tinyagent.core.kernel import Kernel
from tinyagent.core.memory import MemoryStore, PersistentMemorySource
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import default_policy
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.resources import ResourceLoader, ResourceLoaderConfig
from tinyagent.core.skills import SkillRegistry
from tinyagent.core.skills.drafts import draft_from_run, install_draft, list_drafts, reject_draft, show_draft
from tinyagent.extensions.todo_memory import TodoMemoryExtension
from tinyagent.extensions.todo_memory.tools import TodoWriteTool
from tinyagent.core.state import ModelResponse, RunState, ToolCall, Workspace
from tinyagent.core.tools import default_tools


def test_skill_draft_generation_install_and_reject_from_successful_run(tmp_path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / "hello.txt").write_text("hello\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.txt",
            "@@",
            "-hello",
            "+updated",
            "*** End Patch",
        ]
    )
    state = Kernel(
        model=FakeModelProvider(
                [
                    ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                    ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"{sys.executable} -m pytest --version"}),)),
                    ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "hello.txt"}),)),
                    ModelResponse(content="Updated hello.txt. Verification passed with python -m pytest --version.", finish_reason="stop"),
                ]
            ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=default_policy(),
        workspace_mode="current",
    ).run("Update hello.txt and verify pytest is available.", workspace=workspace, run_id="run_skill_draft")

    draft = draft_from_run(Path(state.output_dir), workspace=workspace)
    source = json.loads((draft.path / "source-run.json").read_text())
    status = json.loads((draft.path / "status.json").read_text())
    installed = install_draft(draft.draft_id, workspace=workspace)
    second = draft_from_run(Path(state.output_dir), workspace=workspace)
    rejected = reject_draft(second.draft_id, workspace=workspace)

    assert (draft.path / "SKILL.md").exists()
    assert (draft.path / "eval-plan.md").exists()
    assert (draft.path / "status.json").exists()
    assert source["source_run"]["run_id"] == "run_skill_draft"
    assert source["version"] == 1
    assert source["inputs"]["event_count"] > 0
    assert any(path.startswith("artifacts/model-request") for path in source["inputs"]["hidden_artifacts_skipped"])
    assert status["auto_installed"] is False
    assert source["included_debug_artifacts"] is False
    assert "debug_artifacts" not in source
    assert "## Verification" in show_draft(draft.draft_id, workspace=workspace)
    assert (installed / "SKILL.md").exists()
    assert not (installed / "source-run.json").exists()
    assert not (installed / "eval-plan.md").exists()
    assert rejected.parent.name == "rejected"
    assert [item.draft_id for item in list_drafts(workspace=workspace)] == [draft.draft_id]


def test_skill_draft_eval_writes_comparison_artifacts(tmp_path) -> None:
    from tinyagent.core.skills.drafts import eval_draft

    workspace = tmp_path / "repo"
    workspace.mkdir()
    run = workspace / ".tinyagent" / "runs" / "run_done"
    run.mkdir(parents=True)
    (run / "events.jsonl").write_text(
        json.dumps(
            {
                "id": "evt_1",
                "seq": 1,
                "type": "run.started",
                "time": "2026-05-08T00:00:00Z",
                "run_id": "run_done",
                "turn_id": None,
                "item_id": None,
                "parent_item_id": None,
                "source": "tinyagent",
                "visibility": "debug",
                "durability": "event_log",
                "data": {"task": "inspect hello"},
                "artifact_refs": [],
            },
            sort_keys=True,
        )
        + "\n"
        + json.dumps(
            {
                "id": "evt_2",
                "seq": 2,
                "type": "artifact.finalization.started",
                "time": "2026-05-08T00:00:01Z",
                "run_id": "run_done",
                "turn_id": None,
                "item_id": None,
                "parent_item_id": None,
                "source": "tinyagent",
                "visibility": "debug",
                "durability": "event_log",
                "data": {},
                "artifact_refs": [],
            },
            sort_keys=True,
        )
        + "\n"
        + json.dumps(
            {
                "id": "evt_3",
                "seq": 3,
                "type": "artifact.finalization.completed",
                "time": "2026-05-08T00:00:02Z",
                "run_id": "run_done",
                "turn_id": None,
                "item_id": None,
                "parent_item_id": None,
                "source": "tinyagent",
                "visibility": "debug",
                "durability": "event_log",
                "data": {},
                "artifact_refs": [],
            },
            sort_keys=True,
        )
        + "\n"
        + json.dumps(
            {
                "id": "evt_4",
                "seq": 4,
                "type": "run.completed",
                "time": "2026-05-08T00:00:03Z",
                "run_id": "run_done",
                "turn_id": None,
                "item_id": None,
                "parent_item_id": None,
                "source": "tinyagent",
                "visibility": "debug",
                "durability": "event_log",
                "data": {"status": "completed"},
                "artifact_refs": [],
            },
            sort_keys=True,
        )
        + "\n"
    )
    (run / "metrics.json").write_text('{"run_id":"run_done","status":"completed","task":"inspect hello"}\n')
    (run / "final.md").write_text("done\n")
    (run / "final.diff").write_text("")
    draft = draft_from_run(run, workspace=workspace)
    suite = _write_stage6_suite(tmp_path)

    comparison = eval_draft(
        draft.draft_id,
        workspace=workspace,
        suite_path=suite,
        output_dir=tmp_path / "draft-eval",
        model_factory=lambda task: FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=default_policy(),
    )

    assert [run.variant_name for run in comparison.variants] == ["baseline", "draft"]
    assert (tmp_path / "draft-eval" / "comparison.md").exists()


def test_memory_files_are_explicit_and_optional_context_source(tmp_path) -> None:
    store = MemoryStore(tmp_path)
    store.append("project", "Remember the websocket decision.")
    state = RunState.create("memory", Workspace(tmp_path), run_id="run_memory")
    state.skill_registry = SkillRegistry(())
    state.context_registry = ContextRegistry([*default_context_sources(state.skill_registry), PersistentMemorySource()])

    searched = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "websocket", "source": "memory"}), state)
    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "memory:project"}), state)

    assert (tmp_path / ".tinyagent" / "memory" / "project.md").read_text() == "Remember the websocket decision.\n"
    assert "memory:project" in searched.output
    assert "websocket decision" in read.output
    assert ResourceLoader(ResourceLoaderConfig(memory_enabled=True)).load(tmp_path, profile="tiny-coder").context_sources
    assert ResourceLoader(ResourceLoaderConfig(memory_enabled=True)).load(tmp_path, profile="tiny-pi").context_sources == ()


def test_persistent_memory_and_todo_memory_sources_coexist(tmp_path) -> None:
    MemoryStore(tmp_path).append("project", "Persistent project note.")
    state = RunState.create("memory", Workspace(tmp_path), run_id="run_memory_coexist")
    TodoWriteTool().run(ToolCall(name="todo_write", args={"items": [{"text": "Run todo note"}]}), state)
    extension = TodoMemoryExtension()
    state.skill_registry = SkillRegistry(())
    state.context_registry = ContextRegistry([PersistentMemorySource(), *extension.context_sources()])

    project = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "memory:project"}), state)
    todo = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "memory:todo/current"}), state)

    assert project.ok is True
    assert todo.ok is True
    assert "Persistent project note" in project.output
    assert "Run todo note" in todo.output


def test_cli_memory_commands_write_explicit_files(tmp_path, capsys) -> None:
    from tinyagent.cli import main

    assert main(["memory", "--workspace", str(tmp_path), "append", "decisions", "Use file-backed memory."]) == 0
    assert main(["memory", "--workspace", str(tmp_path), "read", "decisions"]) == 0
    captured = capsys.readouterr()

    assert "Use file-backed memory." in captured.out


def test_evolution_scaffold_accepts_reviewed_skill_candidate(tmp_path) -> None:
    skill_dir = tmp_path / ".tinyagent" / "skills" / "repo-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: repo-review\ndescription: Review diffs.\n---\nUse git diff.\n")
    suite = tmp_path / "evals"
    suite.mkdir()

    experiment = create_skill_experiment(workspace=tmp_path, skill_id="repo-review", suite_path=suite)
    target = tmp_path / ".tinyagent" / "skills" / "repo-review"
    target.rename(tmp_path / ".tinyagent" / "skills" / "repo-review-original")
    accepted = accept_candidate(workspace=tmp_path, candidate_id=f"{experiment.experiment_id}/candidate-1")

    assert (experiment.path / "experiment.json").exists()
    assert "Acceptance requires a human review" in (experiment.report_path).read_text()
    assert (experiment.candidate_path / "SKILL.md").exists()
    assert (accepted / "SKILL.md").exists()


def _write_stage6_suite(tmp_path: Path) -> Path:
    suite = tmp_path / "suite"
    case = suite / "noop"
    case.mkdir(parents=True)
    (case / "task.json").write_text(json.dumps({"id": "noop", "task": "Return done.", "setup_git": False}))
    return suite
