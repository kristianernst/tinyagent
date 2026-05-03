from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from dataclasses import replace

from agentd.context import BuiltContext
from agentd.eval_metrics import evaluate_thresholds, extract_run_metrics
from agentd.kernel import Kernel
from agentd.models import FakeModelProvider
from agentd.policy import LocalPolicy
from agentd.profiles import ApexCoderProfile
from agentd.run_graph import fork_run
from agentd.sdk import Agent
from agentd.state import Message, ModelResponse, PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult, ToolStep, Workspace
from agentd.tools import ShellTool, default_tools


def test_toolresult_contextfs_and_context_report_contracts(tmp_path) -> None:
    call = ToolCall(name="shell", args={"cmd": f"{sys.executable} -c \"print('x' * 80)\""})
    kernel = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(call,)), ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        budgets=RunBudgets(max_command_output_chars_visible=16),
        workspace_mode="current",
    )

    state = kernel.run("produce long output", workspace=tmp_path, run_id="run_contextfs_contract")

    assert state.failed is False
    result = state.tool_results[0]
    assert result.truncated is True
    assert result.artifact_path and result.artifact_path.startswith("context/shell/")
    assert result.read_hints and result.read_hints[0].startswith("tail -120 context/shell/")
    assert (state.output_dir / result.artifact_path).read_text() == ("x" * 80) + "\n"
    index = (state.output_dir / "context" / "INDEX.md").read_text()
    assert result.artifact_path in index
    report_event = next(event for event in state.events if event.type == "context.report.written")
    report = json.loads((state.output_dir / report_event.data["context_report_artifact"]).read_text())
    assert any(item["id"] == "contextfs:index" for item in report["included"])


def test_finish_gate_blocks_edit_without_diff_or_verification(tmp_path) -> None:
    (tmp_path / "hello.txt").write_text("hello\n")
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: hello.txt",
            "@@",
            "-hello",
            "+hello updated",
            "*** End Patch",
        ]
    )
    kernel = Kernel(
        model=FakeModelProvider(
            [
                ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
                ModelResponse(content="done", finish_reason="stop"),
            ]
        ),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        workspace_mode="current",
    )

    state = kernel.run("edit then finish too early", workspace=tmp_path, run_id="run_finish_gate_contract")

    assert state.failed is True
    blocked = next(event for event in state.events if event.type == "finish.blocked")
    assert "inspect git diff" in blocked.data["reason"]


def test_declarative_policy_metadata_and_repeated_command_guard(tmp_path) -> None:
    state = RunState.create("policy", Workspace(tmp_path), run_id="run_policy")
    policy = LocalPolicy()
    network = policy.evaluate(ToolCall(name="shell", args={"cmd": "curl https://example.com"}), state)
    assert network.kind == "deny"
    assert network.permission == "network"
    assert network.matched_rule == "network.deny"

    failed = ToolResult(tool_name="shell", output="failed", ok=False)
    cmd = "false"
    state.tool_steps.extend(
        [
            ToolStep(ToolCall(name="shell", args={"cmd": cmd}), failed),
            ToolStep(ToolCall(name="shell", args={"cmd": cmd}), failed),
        ]
    )
    repeated = policy.evaluate(ToolCall(name="shell", args={"cmd": cmd}), state)
    assert repeated.kind == "deny"
    assert repeated.matched_rule == "bash.repeated_failed_command"


def test_worktree_sandbox_mode_records_enforced_boundary(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    (tmp_path / "hello.txt").write_text("hello\n")
    subprocess.run(["git", "add", "hello.txt"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.email=tinyagent@example.test", "-c", "user.name=tinyagent", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        sandbox_mode="worktree",
    ).run("use worktree sandbox", workspace=tmp_path, run_id="run_worktree_sandbox")

    assert state.workspace.root != tmp_path.resolve()
    boundary = next(event for event in state.events if event.type == "workspace.boundary")
    assert boundary.data["sandbox_mode"] == "worktree"
    assert boundary.data["sandbox_enforced"] is True


def test_hook_can_inject_context_and_block_tool(tmp_path) -> None:
    class BlockingHook:
        name = "blocking-hook"

        def on_context(self, state: RunState, context: BuiltContext) -> BuiltContext:
            return replace(context, messages=[*context.messages, Message(role="user", content="hook context")])

        def before_tool_call(self, state: RunState, call: ToolCall, decision: PolicyDecision) -> ToolResult:
            return ToolResult(tool_name=call.name, call_id=call.id, output="hook blocked", ok=False, failure_kind="policy_denied")

    call = ToolCall(name="shell", args={"cmd": "printf should-not-run"})
    state = Kernel(
        model=FakeModelProvider([ModelResponse(tool_calls=(call,)), ModelResponse(content="blocked by hook", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=[ShellTool()],
        policy=LocalPolicy(),
        hooks=[BlockingHook()],
        workspace_mode="current",
    ).run("hook test", workspace=tmp_path, run_id="run_hook_contract")

    assert state.failed is False
    assert "command.started" not in [event.type for event in state.events]
    assert any(event.type == "hook.completed" and event.data["method"] == "on_context" for event in state.events)
    assert any(event.type == "tool.execution.blocked" for event in state.events)
    first_context = next(event for event in state.events if event.type == "model.call.started")
    assert "hook context" in (state.output_dir / first_context.data["context_artifact"]).read_text()


def test_sdk_streams_same_durable_events_as_run_log(tmp_path) -> None:
    async def collect():
        agent = Agent.create(
            workspace=tmp_path,
            provider=FakeModelProvider([ModelResponse(content="sdk done", finish_reason="stop")]),
            tools=default_tools(),
            policy=LocalPolicy(),
        )
        return [event async for event in agent.run("sdk task", run_id="run_sdk_contract")]

    events = asyncio.run(collect())
    run_dir = tmp_path / ".tinyagent" / "runs" / "run_sdk_contract"
    persisted = [json.loads(line)["id"] for line in (run_dir / "events.jsonl").read_text().splitlines() if line]
    assert [event.id for event in events if event.durability == "event_log"] == persisted


def test_run_graph_fork_metadata_and_eval_thresholds(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done", finish_reason="stop")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
    ).run("fork me", workspace=tmp_path, run_id="run_fork_source")

    destination = fork_run(state.output_dir, "0001", output_dir=tmp_path / "forked")
    metadata = json.loads((destination / "fork.json").read_text())
    assert metadata["parent_run_id"] == state.run_id
    assert metadata["parent_event_seq"] == 1

    metrics = extract_run_metrics(state.output_dir)
    assert metrics.tool_error_count == 0
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text(json.dumps({"min_solve_rate": 1.0, "max_policy_denials": 0, "max_unknown_errors": 0}))
    passing = evaluate_thresholds([{"success": True, "policy_denials": 0, "tool_error_kinds": {}}], thresholds)
    assert passing == []
