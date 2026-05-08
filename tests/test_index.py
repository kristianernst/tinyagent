from __future__ import annotations

import tinyagent.core.index.rg as rg_mod
from tinyagent.core.context_sources import ContextReadTool, ContextRegistry, ContextSearchTool, default_context_sources
from tinyagent.core.index import SearchCodeTool, WorkspaceIndexManager
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import LocalPolicy, PolicyRule, default_policy_config
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.state import ModelResponse, RunBudgets, RunState, ToolCall, Workspace
from tinyagent.core.tools import default_tools


def test_search_code_returns_compact_refs_and_events(tmp_path) -> None:
    (tmp_path / "tiny.py").write_text("def dispatch_tool_call():\n    return 'needle'\n")
    state = RunState.create("search", Workspace(tmp_path), run_id="run_search_code")
    state.workspace_index = WorkspaceIndexManager.for_workspace(tmp_path)

    result = SearchCodeTool().run(ToolCall(name="search_code", args={"query": "dispatch_tool_call", "explain": True}), state)

    assert result.ok is True
    assert "tiny.py" in result.output
    assert "code:tiny.py#L1" in result.output
    assert result.data["result_count"] == 1
    event = next(event for event in state.events if event.type == "code.search.completed")
    assert event.data["query"] == "dispatch_tool_call"
    assert event.data["refs"] == ["code:tiny.py#L1"]
    assert "results" not in event.data


def test_search_code_rg_backend_uses_sanitized_env_and_state_timeout(tmp_path, monkeypatch) -> None:
    (tmp_path / "tiny.py").write_text("needle\n")
    state = RunState.create("search", Workspace(tmp_path), budgets=RunBudgets(max_shell_timeout_seconds=7), run_id="run_search_env")
    state.workspace_index = WorkspaceIndexManager.for_workspace(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    captured = {}

    def fake_run_rg(root, rg, query, target, *, max_matches, env, timeout_seconds):
        captured.update({"root": root, "rg": rg, "query": query, "target": target, "env": env, "timeout_seconds": timeout_seconds})
        return ["tiny.py:1:needle"], False, False

    monkeypatch.setattr(rg_mod.shutil, "which", lambda _name: "/usr/bin/rg")
    monkeypatch.setattr(rg_mod, "_run_rg", fake_run_rg)

    result = SearchCodeTool().run(ToolCall(name="search_code", args={"query": "needle"}), state)

    assert result.ok is True
    assert captured["timeout_seconds"] == 7
    assert "OPENAI_API_KEY" not in captured["env"]
    assert captured["env"]["HOME"] == str(state.output_dir / "home")
    assert captured["env"]["PYTHONDONTWRITEBYTECODE"] == "1"


def test_search_code_file_path_keeps_filename_in_ref(tmp_path) -> None:
    (tmp_path / "tiny.py").write_text("needle\n")
    state = RunState.create("search", Workspace(tmp_path), run_id="run_search_file")
    state.workspace_index = WorkspaceIndexManager.for_workspace(tmp_path)

    result = SearchCodeTool().run(ToolCall(name="search_code", args={"query": "needle", "path": "tiny.py"}), state)

    assert result.ok is True
    assert result.data["results"][0]["ref"] == "code:tiny.py#L1"


def test_workspace_index_context_source_search_and_read(tmp_path) -> None:
    (tmp_path / "tiny.py").write_text("header\n    return 'needle'\n")
    state = RunState.create("search", Workspace(tmp_path), run_id="run_search_code_context")
    state.workspace_index = WorkspaceIndexManager.for_workspace(tmp_path)
    state.context_registry = ContextRegistry(default_context_sources())

    searched = ContextSearchTool().run(
        ToolCall(name="context_search", args={"query": "needle", "source": "workspace_index"}),
        state,
    )
    read = ContextReadTool().run(
        ToolCall(name="context_read", args={"ref": "workspace_index:code:tiny.py#L2", "max_lines": 1}),
        state,
    )

    assert searched.ok is True
    assert "workspace_index:code:tiny.py#L2" in searched.output
    assert read.ok is True
    assert "return 'needle'" in read.output
    assert "header" not in read.output


def test_search_code_policy_blocks_outside_paths(tmp_path) -> None:
    state = RunState.create("search", Workspace(tmp_path), run_id="run_search_policy")

    decision = LocalPolicy().evaluate(ToolCall(name="search_code", args={"query": "x", "path": "../outside"}), state)

    assert decision.kind == "deny"
    assert "outside workspace" in decision.reason


def test_workspace_index_context_read_blocks_protected_env(tmp_path) -> None:
    (tmp_path / ".env").write_text("SECRET=needle\n")
    state = RunState.create("search", Workspace(tmp_path), run_id="run_search_secret")
    state.workspace_index = WorkspaceIndexManager.for_workspace(tmp_path)
    state.context_registry = ContextRegistry(default_context_sources())

    direct = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "workspace_index:code:.env"}), state)
    decision = LocalPolicy().evaluate(ToolCall(name="context_read", args={"ref": "workspace_index:code:.env"}), state)

    assert direct.ok is False
    assert decision.kind == "deny"
    assert "protected environment file" in decision.reason


def test_search_code_semantic_mode_is_explicitly_unavailable(tmp_path) -> None:
    (tmp_path / "tiny.py").write_text("needle\n")
    state = RunState.create("search", Workspace(tmp_path), run_id="run_search_semantic")
    state.workspace_index = WorkspaceIndexManager.for_workspace(tmp_path)

    result = SearchCodeTool().run(ToolCall(name="search_code", args={"query": "needle", "mode": "semantic"}), state)

    assert result.ok is False
    assert result.failure_kind == "unsupported_mode"
    assert "semantic search is unavailable" in result.output


def test_search_code_kind_filter(tmp_path) -> None:
    (tmp_path / "notes.md").write_text("needle\n")
    (tmp_path / "tiny.py").write_text("needle\n")
    state = RunState.create("search", Workspace(tmp_path), run_id="run_search_kind")
    state.workspace_index = WorkspaceIndexManager.for_workspace(tmp_path)

    result = SearchCodeTool().run(ToolCall(name="search_code", args={"query": "needle", "kind": "doc"}), state)

    refs = [item["ref"] for item in result.data["results"]]
    assert refs == ["code:notes.md#L1"]


def test_context_search_without_source_honors_skill_policy(tmp_path) -> None:
    state = RunState.create("search", Workspace(tmp_path), run_id="run_context_search_policy")
    config = default_policy_config()
    policy = LocalPolicy(config=type(config)(default=config.default, rules=(*config.rules, PolicyRule("skill", "*", "deny"))))

    decision = policy.evaluate(ToolCall(name="context_search", args={"query": "python"}), state)

    assert decision.kind == "deny"
    assert decision.permission == "skill"


def test_workspace_index_manager_creates_product_home_search_dir(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    manager = WorkspaceIndexManager.for_workspace(tmp_path)

    assert manager.index_root is not None
    assert manager.index_root.exists()
    assert manager.index_root.parent.name.startswith("ws_")


def test_kernel_initializes_product_home_workspace_index(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    ).run("done", workspace=workspace, output_dir=tmp_path / "run")

    assert isinstance(state.workspace_index, WorkspaceIndexManager)
    assert state.workspace_index.index_root is not None
    assert state.workspace_index.index_root.is_relative_to(home / "workspaces")


def test_kernel_records_profile_metadata_on_run_started(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("TINYAGENT_HOME", str(home))

    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    ).run("done", workspace=workspace, output_dir=tmp_path / "run")

    started = next(event for event in state.events if event.type == "run.started")
    assert started.data["profile"] == "tiny-coder"
    assert started.data["profile_variant"] == "default"
    assert started.data["context_policy"] == "dynamic-v1"
    assert started.data["skill_policy"] == "default-v1"
    assert started.data["tool_surface"] == "default"
    assert started.data["system_prompt_hash"]
    assert "search_code" in started.data["profile_visible_tools"]
