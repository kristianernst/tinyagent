from __future__ import annotations

import subprocess
from collections.abc import Sequence

from tinyagent.core.context import ContextConfig, load_project_instructions
from tinyagent.core.contracts import Tool
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import LocalPolicy
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.state import Message, ModelResponse, RunState, ToolCall, ToolResult, ToolStep, Workspace
from tinyagent.core.tools import default_tools


class RecordingModel:
    name = "recording"

    def __init__(self, responses: Sequence[ModelResponse]) -> None:
        self.responses = list(responses)
        self.messages: list[list[Message]] = []

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        del tools, state
        self.messages.append(list(messages))
        return self.responses.pop(0)


def test_project_instructions_load_global_then_git_root_to_leaf(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    global_dir = home / ".tinyagent"
    global_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    (global_dir / "AGENTS.md").write_text("global instructions\n")

    repo = tmp_path / "repo"
    package = repo / "pkg"
    package.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    (repo / "AGENTS.md").write_text("root instructions\n")
    (package / "AGENTS.md").write_text("leaf instructions\n")

    instructions = load_project_instructions(package, ContextConfig(project_instruction_max_chars=10_000))

    assert instructions.files == (
        str(global_dir / "AGENTS.md"),
        str(repo / "AGENTS.md"),
        str(package / "AGENTS.md"),
    )
    assert instructions.content.index("global instructions") < instructions.content.index("root instructions")
    assert instructions.content.index("root instructions") < instructions.content.index("leaf instructions")


def test_project_instructions_cap_truncates_content(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    instructions_path = tmp_path / "AGENTS.md"
    instructions_path.write_text("first\nsecond\n")
    header = f"## {instructions_path.resolve()}\n\n"

    instructions = load_project_instructions(
        tmp_path,
        ContextConfig(project_instruction_max_chars=len(header) + len("first")),
    )

    assert instructions.truncated is True
    assert "first" in instructions.content
    assert "second" not in instructions.content


def test_apex_context_layers_environment_agents_task_and_budgeted_tools(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "AGENTS.md").write_text("Prefer rg before grep.\n")
    state = RunState.create("inspect and patch", Workspace(tmp_path), run_id="run_context")
    state.shell_preflight = {"commands": {"rg": True, "git": False}, "python_available": True}
    state.tool_steps.extend(
        [
            ToolStep(
                call=ToolCall(name="shell", args={"cmd": "printf older-noise"}),
                result=ToolResult(tool_name="shell", output="older-noise", data={"cmd": "printf older-noise"}),
            ),
            ToolStep(
                call=ToolCall(name="shell", args={"cmd": "false"}),
                result=ToolResult(tool_name="shell", output="failed command", ok=False, data={"cmd": "false", "returncode": 1}),
            ),
            ToolStep(
                call=ToolCall(name="shell", args={"cmd": "git status --short"}),
                result=ToolResult(tool_name="shell", output=" M file.py", data={"cmd": "git status --short"}),
            ),
            ToolStep(
                call=ToolCall(name="apply_patch", args={"patch": "*** Begin Patch\n*** End Patch"}),
                result=ToolResult(tool_name="apply_patch", output="Applied patch.", data={"paths": ["file.py"]}),
            ),
        ]
    )
    profile = ApexCoderProfile(context_config=ContextConfig(max_recent_tool_tokens=1, compact_at_tokens=999_999))

    built = profile.build_context(state)

    assert [message.meta.get("context_layer") for message in built.messages[1:]] == [
        "environment",
        "project_instructions",
        "task",
        "context_plan",
        "working_state",
        "recent_tool_steps",
    ]
    environment = built.messages[1].content
    assert "cwd:" in environment
    assert "shell_preflight:" in environment
    assert "git: False" in environment
    assert "rg: True" in environment
    assert "python_available: True" in environment
    assert "sandbox_mode: none" in environment
    assert "Prefer rg before grep." in built.messages[2].content
    assert built.messages[3].content == "Task:\ninspect and patch"
    assert "mode: debug" in built.messages[4].content
    recent = built.messages[-1].content
    assert "failed command" in recent
    assert "git status --short" in recent
    assert "Applied patch." in recent
    assert "older-noise" not in recent


def test_apex_context_includes_prior_conversation_before_current_task(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    state = RunState.create(
        "current request",
        Workspace(tmp_path),
        run_id="run_prior_context",
        prior_messages=[
            Message(role="user", content="previous question"),
            Message(role="assistant", content="previous answer"),
        ],
    )
    state.prior_context_artifact = "artifacts/prior-context.json"
    profile = ApexCoderProfile(context_config=ContextConfig(compact_at_tokens=999_999))

    built = profile.build_context(state)
    layers = [message.meta.get("context_layer") for message in built.messages]

    assert layers.index("conversation_history") < layers.index("task")
    conversation = next(message.content for message in built.messages if message.meta.get("context_layer") == "conversation_history")
    assert "previous question" in conversation
    assert "previous answer" in conversation
    assert "artifacts/prior-context.json" in conversation


def test_kernel_compacts_at_turn_boundary_and_uses_checkpoint(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    model = RecordingModel(
        [
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "printf 'test output\\n'"}),)),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    profile = ApexCoderProfile(context_config=ContextConfig(compact_at_tokens=1, max_recent_tool_tokens=10))
    kernel = Kernel(
        model=model,
        profile=profile,
        tools=default_tools(),
        policy=LocalPolicy(),
    )

    state = kernel.run("run a command then finish", workspace=tmp_path, run_id="run_compact")

    assert state.failed is False
    assert state.compaction_count == 1
    assert state.context_checkpoint_artifact == "artifacts/context-checkpoint-0001.md"
    checkpoint = (state.output_dir / state.context_checkpoint_artifact).read_text()
    assert "## Commands Run" in checkpoint
    assert "printf 'test output\\n'" in checkpoint
    assert "command-output" in checkpoint
    assert [event.type for event in state.events if event.type in {"compaction.started", "checkpoint.completed"}] == [
        "compaction.started",
        "checkpoint.completed",
    ]
    context_built = [event for event in state.events if event.type == "context.built"][-1]
    assert context_built.data["token_estimate"] == state.context_token_estimate
    assert context_built.data["checkpoint_artifact"] == state.context_checkpoint_artifact

    second_request = model.messages[1]
    working_state = next(message for message in second_request if message.meta.get("context_layer") == "working_state")
    recent_tools = next(message for message in second_request if message.meta.get("context_layer") == "recent_tool_steps")
    assert "Previous checkpoint:" in working_state.content
    assert "Context Checkpoint 1" in working_state.content
    assert "None since the last checkpoint." in recent_tools.content


def test_kernel_compacts_after_configured_tool_step_count(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    model = RecordingModel(
        [
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "printf 'step trigger\\n'"}),)),
            ModelResponse(content="done", finish_reason="stop"),
        ]
    )
    profile = ApexCoderProfile(
        context_config=ContextConfig(
            compact_after_tool_steps=1,
            compact_at_tokens=999_999,
            max_recent_tool_tokens=10,
        )
    )
    kernel = Kernel(
        model=model,
        profile=profile,
        tools=default_tools(),
        policy=LocalPolicy(),
    )

    state = kernel.run("compact after one tool step", workspace=tmp_path, run_id="run_compact_steps")

    assert state.failed is False
    assert state.compaction_count == 1
    assert state.context_checkpoint_tool_step_count == 1
    assert state.context_token_estimate < profile.context_config.effective_compact_at_tokens
    assert state.context_checkpoint_artifact == "artifacts/context-checkpoint-0001.md"
    second_request = model.messages[1]
    working_state = next(message for message in second_request if message.meta.get("context_layer") == "working_state")
    recent_tools = next(message for message in second_request if message.meta.get("context_layer") == "recent_tool_steps")
    assert "Context Checkpoint 1" in working_state.content
    assert state.context_checkpoint_artifact in working_state.content
    assert "None since the last checkpoint." in recent_tools.content


def test_fake_model_remains_usable_with_layered_context(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    state = RunState.create("fake context", Workspace(tmp_path), run_id="run_fake_context")
    profile = ApexCoderProfile()

    response = FakeModelProvider([ModelResponse(content="ok")]).complete(profile.build_messages(state), [], state)

    assert response.content == "ok"
