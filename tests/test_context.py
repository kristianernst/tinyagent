from __future__ import annotations

import subprocess
from collections.abc import Sequence

from tinyagent.core.context import ContextConfig, load_project_instructions
from tinyagent.core.context.checkpoint import artifact_refs_from_tool_steps
from tinyagent.core.contracts import Tool
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.observations import Observation
from tinyagent.core.policy import LocalPolicy
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.state import Message, ModelRequestContext, ModelResponse, PolicyDecision, RunState, ToolCall, ToolResult, ToolStep, Workspace
from tinyagent.core.token_utils import estimate_tokens
from tinyagent.core.tools import default_tools


class WorkspaceShellPolicy(LocalPolicy):
    def _evaluate_shell(self, call: ToolCall, state: RunState) -> PolicyDecision:
        decision = super()._evaluate_shell(call, state)
        if decision.kind == "needs_approval" and decision.permission == "bash":
            return PolicyDecision.allow("test permits workspace shell", matched_rule="test.bash.allow", permission="bash")
        return decision


class RecordingModel:
    name = "recording"

    def __init__(self, responses: Sequence[ModelResponse]) -> None:
        self.responses = list(responses)
        self.messages: list[list[Message]] = []

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> ModelResponse:
        del tools, request
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

    instructions = load_project_instructions(package, ContextConfig(project_instruction_max_tokens=10_000))

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
        ContextConfig(project_instruction_max_tokens=estimate_tokens(header + "first")),
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
        "dynamic_context_sources",
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
    assert "mode: verify" in built.messages[4].content
    assert "Use context_search" in built.messages[5].content
    recent = built.messages[-1].content
    assert "failed command" in recent
    assert "git status --short" in recent
    assert "Applied patch." in recent
    assert "older-noise" not in recent


def test_apex_context_debug_mode_only_tracks_active_failures(tmp_path) -> None:
    state = RunState.create("recover after transient failure", Workspace(tmp_path), run_id="run_context_recovery")
    state.tool_steps.extend(
        [
            ToolStep(
                call=ToolCall(name="shell", args={"cmd": "pytest"}),
                result=ToolResult(tool_name="shell", output="failed", ok=False, data={"cmd": "pytest"}, exit_code=1),
            ),
            ToolStep(
                call=ToolCall(name="shell", args={"cmd": "pytest"}),
                result=ToolResult(tool_name="shell", output="passed", data={"cmd": "pytest"}, exit_code=0),
            ),
        ]
    )
    profile = ApexCoderProfile(context_config=ContextConfig(compact_at_tokens=999_999))

    recovered = profile.plan_next_context(state)
    state.tool_steps.append(
        ToolStep(
            call=ToolCall(name="shell", args={"cmd": "pytest"}),
            result=ToolResult(tool_name="shell", output="failed again", ok=False, data={"cmd": "pytest"}, exit_code=1),
        )
    )

    assert recovered.mode != "debug"
    assert profile.plan_next_context(state).mode == "debug"


def test_recent_tool_context_uses_stable_contextfs_refs_for_product_home_output(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    output_dir = tmp_path / "home" / ".tinyagent" / "runs" / "run_product_home_recent"
    workspace.mkdir()
    artifact = output_dir / "context" / "shell" / "0001-call_shell.txt"
    state = RunState.create("inspect product home", Workspace(workspace), run_id="run_product_home_recent", output_dir=output_dir)
    state.tool_steps.append(
        ToolStep(
            call=ToolCall(id="call_shell", name="shell", args={"cmd": "printf x"}),
            result=ToolResult(
                tool_name="shell",
                call_id="call_shell",
                output="x" * 100,
                artifact_path="context/shell/0001-call_shell.txt",
                read_hints=[f"tail -120 {artifact}"],
            ),
        )
    )
    state.observations.append(
        Observation(
            kind="file_changed",
            subject="research/iphone-costs.md",
            summary="research/iphone-costs.md changed by write_file.",
            refs=("context/patch/0002-call_write.txt", "artifacts/edit-output-call_write.txt"),
        )
    )
    profile = ApexCoderProfile(context_config=ContextConfig(max_recent_tool_tokens=999_999, compact_at_tokens=999_999))

    built = profile.build_context(state)

    recent = next(message for message in built.messages if message.meta.get("context_layer") == "recent_tool_steps")
    assert 'context_read({"ref":"contextfs:context/shell/0001-call_shell.txt"})' in recent.content
    assert str(output_dir) not in recent.content
    assert str(output_dir.parent.parent) not in recent.content


def test_recent_tool_context_hides_unreadable_artifacts_when_context_read_is_hidden(tmp_path) -> None:
    state = RunState.create("research prices", Workspace(tmp_path), run_id="run_hidden_context_artifacts")
    state.prior_messages = [Message(role="user", content="previous turn"), Message(role="assistant", content="previous answer")]
    state.prior_context_artifact = "artifacts/prior-context.json"
    state.tool_steps.append(
        ToolStep(
            call=ToolCall(id="call_fetch", name="fetch_url", args={"url": "https://example.test/source"}),
            result=ToolResult(
                tool_name="fetch_url",
                call_id="call_fetch",
                output="Fetched source text with the usable evidence.",
                artifact_path="context/fetch_url/0001-call_fetch.txt",
                read_hints=["tail -120 .tinyagent/runs/run_hidden_context_artifacts/context/fetch_url/0001-call_fetch.txt"],
                data={
                    "url": "https://example.test/source",
                    "context_artifact": "context/fetch_url/0001-call_fetch.txt",
                    "output_artifact": "artifacts/fetch-url-output-call_fetch.txt",
                    "captured_output_artifact": "artifacts/fetch-url-output-call_fetch.txt",
                    "output_tokens": 1024,
                    "workspace_delta": {
                        "diff_artifact": "artifacts/workspace-delta-0001.patch",
                        "paths": ["research/iphone-costs.md"],
                    },
                },
            ),
        )
    )
    profile = ApexCoderProfile(
        visible_tool_names=("read_file", "web_search", "fetch_url", "write_file"),
        context_config=ContextConfig(max_recent_tool_tokens=999_999, compact_at_tokens=999_999),
    )

    built = profile.build_context(state)

    recent = next(message for message in built.messages if message.meta.get("context_layer") == "recent_tool_steps")
    full_text = "\n".join(message.content for message in built.messages if isinstance(message.content, str))
    assert "Fetched source text with the usable evidence." in recent.content
    assert '"url": "https://example.test/source"' in recent.content
    assert "context/fetch_url" not in full_text
    assert "context/patch" not in full_text
    assert "artifacts/fetch-url-output" not in full_text
    assert "artifacts/edit-output" not in full_text
    assert "artifacts/workspace-delta" not in full_text
    assert "artifacts/prior-context" not in full_text
    assert "Artifact:" not in full_text
    assert "tail -120" not in full_text
    assert "context_read(" not in full_text
    assert "contextfs:" not in full_text


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
    on_context_saw_checkpoint: list[bool] = []
    before_compact_seen_events: list[list[str]] = []

    class CompactHook:
        name = "compact-hook"

        def before_compact(self, state: RunState) -> None:
            before_compact_seen_events.append([event.type for event in state.events])

        def on_context(self, state: RunState, context):
            del state
            on_context_saw_checkpoint.append(any("Context Checkpoint 1" in message.content for message in context.messages))
            return context

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
        policy=WorkspaceShellPolicy(),
        hooks=[CompactHook()],
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
    types = [event.type for event in state.events]
    compact_started = types.index("compaction.started")
    hook_started = next(
        index
        for index, event in enumerate(state.events)
        if event.type == "hook.started" and event.data["method"] == "before_compact"
    )
    hook_completed = next(
        index
        for index, event in enumerate(state.events)
        if event.type == "hook.completed" and event.data["method"] == "before_compact"
    )
    checkpoint_completed = types.index("checkpoint.completed")
    context_built_index = next(
        index
        for index, event_type in enumerate(types)
        if index > checkpoint_completed and event_type == "context.built"
    )
    context_report_index = next(
        index for index, event_type in enumerate(types) if index > context_built_index and event_type == "context.report.written"
    )
    model_started_index = next(
        index
        for index, event_type in enumerate(types)
        if index > context_report_index and event_type == "model.call.started"
    )
    assert len(before_compact_seen_events) == 1
    assert before_compact_seen_events[0][-2:] == ["compaction.started", "hook.started"]
    assert "checkpoint.completed" not in before_compact_seen_events[0]
    assert compact_started < hook_started < hook_completed < checkpoint_completed
    assert checkpoint_completed < context_built_index < context_report_index < model_started_index
    assert on_context_saw_checkpoint == [False, True]
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
        policy=WorkspaceShellPolicy(),
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


def test_artifact_refs_from_tool_steps_skips_empty_refs_and_dedupes() -> None:
    steps = [
        ToolStep(
            call=ToolCall(name="shell", id="call_1"),
            result=ToolResult(
                tool_name="shell",
                output="ok",
                data={"context_artifact": "", "output_artifact": "artifacts/output.txt"},
            ),
        ),
        ToolStep(
            call=ToolCall(name="shell", id="call_2"),
            result=ToolResult(
                tool_name="shell",
                output="ok",
                data={"context_artifact": "artifacts/output.txt", "captured_output_artifact": "artifacts/captured.txt"},
            ),
        ),
    ]

    refs = artifact_refs_from_tool_steps(steps)

    assert [ref.path for ref in refs] == ["artifacts/output.txt", "artifacts/captured.txt"]
