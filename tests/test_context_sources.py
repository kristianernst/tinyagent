from __future__ import annotations

from tinyagent.core.context_sources import ContextReadTool, ContextRegistry, ContextSearchTool, default_context_sources
from tinyagent.core.contextfs import refresh_contextfs
from tinyagent.core.policy import LocalPolicy, PolicyConfig, PolicyRule
from tinyagent.core.skills import SkillRegistry
from tinyagent.core.state import Message, RunState, ToolCall, ToolResult, ToolStep, Workspace


def _state(tmp_path, *, prior_messages=()) -> RunState:
    state = RunState.create("debug pytest failure", Workspace(tmp_path), run_id="run_context_sources", prior_messages=prior_messages)
    state.skill_registry = SkillRegistry()
    state.context_registry = ContextRegistry(default_context_sources(state.skill_registry))
    refresh_contextfs(state)
    return state


def test_context_search_and_contextfs_ref_read(tmp_path) -> None:
    state = _state(tmp_path)

    searched = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "debug pytest", "source": "contextfs"}), state)
    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "contextfs:context/task.md"}), state)

    assert searched.ok is True
    assert "contextfs:context/task.md" in searched.output
    assert searched.data["results"][0]["ref"].startswith("contextfs:")
    assert read.ok is True
    assert "debug pytest failure" in read.output
    assert [event.type for event in state.events if event.type in {"context.search.completed", "context.ref.read"}] == [
        "context.search.completed",
        "context.ref.read",
    ]


def test_contextfs_index_uses_stable_refs_when_output_dir_is_outside_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    output_dir = tmp_path / "home" / ".tinyagent" / "runs" / "run_product_home"
    workspace.mkdir()
    state = RunState.create("product home refs", Workspace(workspace), run_id="run_product_home", output_dir=output_dir)
    tool_artifact = output_dir / "context" / "shell" / "0001-call_shell.txt"
    tool_artifact.parent.mkdir(parents=True)
    tool_artifact.write_text("tool output\n")
    state.tool_steps.append(
        ToolStep(
            call=ToolCall(id="call_shell", name="shell"),
            result=ToolResult(
                tool_name="shell",
                call_id="call_shell",
                output="tool output",
                artifact_path="context/shell/0001-call_shell.txt",
                read_hints=[f"tail -120 {tool_artifact}"],
            ),
        )
    )

    refresh_contextfs(state)

    index = (state.output_dir / "context" / "INDEX.md").read_text()
    assert "context/task.md" in index
    assert "context/current_status.md" in index
    assert "context/shell/0001-call_shell.txt" in index
    assert 'context_read({"ref":"contextfs:context/shell/0001-call_shell.txt"})' in index
    assert str(output_dir) not in index
    assert str(output_dir.parent.parent) not in index


def test_context_search_reads_prior_conversation(tmp_path) -> None:
    state = _state(tmp_path, prior_messages=(Message(role="user", content="Remember the checkout failure."),))

    searched = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "checkout", "source": "conversation"}), state)
    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "conversation:prior/1"}), state)

    assert searched.ok is True
    assert "conversation:prior/1" in searched.output
    assert read.ok is True
    assert "checkout failure" in read.output


def test_context_search_reads_past_run_final_output(tmp_path) -> None:
    old_run = tmp_path / ".tinyagent" / "runs" / "run_old"
    old_run.mkdir(parents=True)
    (old_run / "final.md").write_text("# Final output\n\nfixed websocket regression\n")
    (old_run / "metrics.json").write_text('{"task":"websocket bug"}\n')
    state = _state(tmp_path)

    searched = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "websocket", "source": "past_runs"}), state)
    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "past_runs:run_old/final.md"}), state)

    assert searched.ok is True
    assert "past_runs:run_old/final.md" in searched.output
    assert read.ok is True
    assert "fixed websocket regression" in read.output


def test_context_search_reads_skill_without_loading_all_bodies(tmp_path) -> None:
    skill_root = tmp_path / ".tinyagent" / "skills"
    skill_dir = skill_root / "repo-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: repo-review\ndescription: Review repository changes.\n---\nUse git diff.\n")
    state = _state(tmp_path)

    searched = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "repository", "source": "skills"}), state)
    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "skills:skill_project_repo_review/SKILL.md"}), state)

    assert searched.ok is True
    assert "Review repository changes." in searched.output
    assert "Use git diff." not in searched.output
    assert read.ok is True
    assert "Use git diff." in read.output


def test_context_read_denies_unsafe_artifact_ref(tmp_path) -> None:
    state = _state(tmp_path)
    artifact = state.output_dir / "artifacts" / "model-response-0001.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{}\n")

    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "contextfs:artifacts/model-response-0001.json"}), state)

    assert read.ok is False
    assert "not an allowed recovery file" in read.output


def test_context_read_denies_past_run_traversal(tmp_path) -> None:
    state = _state(tmp_path)
    outside = state.output_dir.parent.parent / "final.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("outside\n")

    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "past_runs:../final.md"}), state)

    assert read.ok is False
    assert "Unsafe past-run ref" in read.output


def test_context_registry_combines_results_and_respects_source_filter(tmp_path) -> None:
    state = _state(tmp_path, prior_messages=(Message(role="user", content="pytest context in conversation"),))

    combined = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "pytest", "limit": 10}), state)
    filtered = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "pytest", "source": "conversation"}), state)

    assert combined.ok is True
    assert "contextfs:" in combined.output
    assert "conversation:" in combined.output
    assert filtered.ok is True
    assert "conversation:" in filtered.output
    assert "contextfs:" not in filtered.output


def test_context_read_policy_can_deny_source(tmp_path) -> None:
    state = _state(tmp_path)
    decision = LocalPolicy().evaluate(ToolCall(name="context_read", args={"ref": "unknown:todo/current"}), state)

    assert decision.kind == "deny"
    assert decision.permission == "context_read"


def test_context_read_skill_ref_honors_skill_policy(tmp_path) -> None:
    state = _state(tmp_path)
    policy = LocalPolicy(config=PolicyConfig(default="allow", rules=(PolicyRule("skill", "*", "deny"),)))

    decision = policy.evaluate(ToolCall(name="context_read", args={"ref": "skills:skill_project_review/SKILL.md"}), state)

    assert decision.kind == "deny"
    assert decision.permission == "skill"


def test_context_search_skills_honors_skill_policy(tmp_path) -> None:
    state = _state(tmp_path)
    policy = LocalPolicy(config=PolicyConfig(default="allow", rules=(PolicyRule("skill", "*", "deny"),)))

    decision = policy.evaluate(ToolCall(name="context_search", args={"query": "review", "source": "skills"}), state)

    assert decision.kind == "deny"
    assert decision.permission == "skill"


def test_conversation_read_rejects_zero_index(tmp_path) -> None:
    state = _state(tmp_path, prior_messages=(Message(role="user", content="first"),))

    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "conversation:prior/0"}), state)

    assert read.ok is False


def test_contextfs_read_rejects_large_allowed_file(tmp_path) -> None:
    state = _state(tmp_path)
    large = state.output_dir / "context" / "last_failure.md"
    large.write_text("x" * 1_000_001)

    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "contextfs:context/last_failure.md"}), state)

    assert read.ok is False
    assert "too large" in read.output


def test_context_search_skips_large_contextfs_file_and_returns_other_matches(tmp_path) -> None:
    state = _state(tmp_path)
    large = state.output_dir / "context" / "last_failure.md"
    large.write_text("needle " + ("x" * 1_000_001))
    task = state.output_dir / "context" / "task.md"
    task.write_text("# Task\n\nneedle in safe file\n")

    searched = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "needle", "source": "contextfs"}), state)

    assert searched.ok is True
    assert "contextfs:context/task.md" in searched.output
    assert "contextfs:context/last_failure.md" not in searched.output
