from __future__ import annotations

import asyncio
import json
import os
import queue
import time
from collections.abc import Mapping, Sequence

import pytest

from tinyagent.core.contracts import Tool
from tinyagent.core.policy import LocalPolicy, PolicyConfig, PolicyRule
from tinyagent.core.sdk import Agent, ApprovalContext, SDKRunError, UnsupportedOperationError
from tinyagent.core.state import (
    ApprovalRequest,
    ApprovalResolution,
    Message,
    ModelRequestContext,
    ModelResponse,
    PolicyDecision,
    RunState,
    ToolCall,
    ToolResult,
)
from tinyagent.core.tools import default_tools


class _BasicProfile:
    name = "sdk-test"

    def system_prompt(self) -> str:
        return "sdk test profile"

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return [Message(role="system", content=self.system_prompt()), Message(role="user", content=state.task)]

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        return list(all_tools.values())

    def should_continue(self, state: RunState) -> bool:
        return not state.done

    def should_finish(self, state: RunState) -> bool:
        return False


class _StaticModel:
    name = "sdk-static"

    def __init__(self, responses: Sequence[ModelResponse]) -> None:
        self.responses = list(responses)

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> ModelResponse:
        del messages, tools, request
        if not self.responses:
            return ModelResponse(content="done", finish_reason="stop")
        return self.responses.pop(0)


class _ApprovalPolicy:
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        return PolicyDecision.needs_approval(
            f"{call.name} requires approval",
            ApprovalRequest(
                approval_id=f"approval_{call.id}",
                run_id=state.run_id,
                turn_id=state.current_turn_id,
                step_id=state.current_step_id,
                action_kind="unknown",
                tool_name=call.name,
                cwd=str(state.workspace.root),
                args_preview=str(call.args),
                command=None,
                risk="low",
            ),
        )


class _NoopTool:
    name = "noop"
    schema = {"name": "noop", "parameters": {"type": "object", "properties": {}}}

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        del state
        return ToolResult(tool_name=self.name, call_id=call.id, output="ok")


def test_sdk_start_returns_handle_with_run_id_before_events_and_result(tmp_path) -> None:
    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel([ModelResponse(content="sdk done", finish_reason="stop")]),
            profile=_BasicProfile(),
            tools=default_tools(),
            policy=LocalPolicy(),
        )
        handle = await agent.start("sdk task")
        assert handle.run_id.startswith("run_")
        return handle, await handle.result()

    handle, result = asyncio.run(run())

    assert result.run_id == handle.run_id
    assert result.status == "completed"
    assert result.final_output == "sdk done"
    assert (result.output_dir / "events.jsonl").exists()
    assert result.events[-1].type == "run.completed"


def test_sdk_prompt_alias_lists_and_reads_recorded_runs(tmp_path) -> None:
    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel([ModelResponse(content="sdk prompt done", finish_reason="stop")]),
            profile=_BasicProfile(),
            tools=default_tools(),
            policy=LocalPolicy(),
        )
        result = await agent.prompt("sdk task", run_id="run_sdk_prompt")
        return agent, result

    agent, result = asyncio.run(run())

    assert result.status == "completed"
    assert result.final_output == "sdk prompt done"
    assert agent.supports("prompt") is True
    assert agent.supports("run") is True
    assert agent.supports("run_once") is True
    assert agent.supports("read_run") is True
    assert agent.supports("wait") is False
    assert agent.supports("resume") is False
    summaries = agent.list_runs()
    assert [summary.run_id for summary in summaries] == ["run_sdk_prompt"]
    recorded = agent.read_run("run_sdk_prompt")
    assert recorded.run_id == "run_sdk_prompt"
    assert recorded.final_output == "sdk prompt done"
    assert recorded.context_usage["context_token_estimate"] >= 0
    assert recorded.output_dir == result.output_dir


def test_sdk_start_rejects_invalid_run_id(tmp_path) -> None:
    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel([ModelResponse(content="unused", finish_reason="stop")]),
            profile=_BasicProfile(),
            tools=default_tools(),
            policy=LocalPolicy(),
        )
        with pytest.raises(ValueError, match="invalid run_id"):
            await agent.start("sdk task", run_id="../outside")

    asyncio.run(run())


def test_sdk_recorded_run_access_rejects_symlinked_run_dirs_and_tampered_paths(tmp_path) -> None:
    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel([ModelResponse(content="sdk done", finish_reason="stop")]),
            profile=_BasicProfile(),
            tools=default_tools(),
            policy=LocalPolicy(),
        )
        await agent.prompt("sdk task", run_id="run_sdk_safe")
        return agent

    agent = asyncio.run(run())
    runs_root = tmp_path / ".tinyagent" / "runs"
    outside_run = tmp_path.parent / f"{tmp_path.name}-outside-run"
    outside_run.mkdir()
    os.symlink(outside_run, runs_root / "run_link")

    assert "run_link" not in [summary.run_id for summary in agent.list_runs()]
    with pytest.raises(ValueError, match="symlink"):
        agent.read_run("run_link")

    secret = tmp_path / "secret.txt"
    secret.write_text("secret\n")
    metrics_path = runs_root / "run_sdk_safe" / "metrics.json"
    metrics = json.loads(metrics_path.read_text())
    metrics["final_output_path"] = str(secret)
    metrics_path.write_text(json.dumps(metrics))

    with pytest.raises(ValueError, match="relative path"):
        agent.read_run("run_sdk_safe")


def test_sdk_events_is_single_consumer_and_drains_terminal_event(tmp_path) -> None:
    async def run() -> tuple[list[str], str]:
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel([ModelResponse(content="sdk done", finish_reason="stop")]),
            profile=_BasicProfile(),
            tools=default_tools(),
            policy=LocalPolicy(),
        )
        handle = await agent.start("sdk task", run_id="run_sdk_events")
        event_types = [event.type async for event in handle.events()]
        with pytest.raises(RuntimeError, match="single-consumer"):
            async for _event in handle.events():
                pass
        result = await handle.result()
        return event_types, result.status

    event_types, status = asyncio.run(run())

    assert event_types[-1] == "run.completed"
    assert status == "completed"


def test_sdk_run_handle_stream_wait_and_supports_aliases(tmp_path) -> None:
    async def run() -> tuple[list[str], str, bool, bool]:
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel([ModelResponse(content="sdk done", finish_reason="stop")]),
            profile=_BasicProfile(),
            tools=default_tools(),
            policy=LocalPolicy(),
        )
        handle = await agent.start("sdk task", run_id="run_sdk_stream_wait")
        event_types = [event.type async for event in handle.stream()]
        result = await handle.wait()
        return event_types, result.status, handle.supports("stream"), handle.supports("cancel"), handle.supports("prompt")

    event_types, status, stream_supported, cancel_supported, prompt_supported = asyncio.run(run())

    assert event_types[-1] == "run.completed"
    assert status == "completed"
    assert stream_supported is True
    assert cancel_supported is True
    assert prompt_supported is False


def test_sdk_stream_wraps_kernel_startup_exceptions(tmp_path) -> None:
    async def run():
        agent = Agent.create(
            workspace=tmp_path / "missing",
            provider=_StaticModel([ModelResponse(content="unused", finish_reason="stop")]),
            profile=_BasicProfile(),
            tools=default_tools(),
            policy=LocalPolicy(),
        )
        handle = await agent.start("sdk task", run_id="run_sdk_missing_workspace")
        with pytest.raises(SDKRunError) as exc:
            async for _event in handle.stream():
                pass
        return exc.value

    error = asyncio.run(run())

    assert error.run_id == "run_sdk_missing_workspace"
    assert error.phase == "run"


def test_sdk_resume_reports_unsupported_reason(tmp_path) -> None:
    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel([ModelResponse(content="unused", finish_reason="stop")]),
            profile=_BasicProfile(),
            tools=default_tools(),
            policy=LocalPolicy(),
        )
        with pytest.raises(UnsupportedOperationError) as exc:
            await agent.resume("run_missing")
        return exc.value

    error = asyncio.run(run())

    assert error.operation == "resume"
    assert "not implemented" in error.reason


def test_sdk_async_approval_callback_approves_tool(tmp_path) -> None:
    async def approve(request: ApprovalRequest, context: ApprovalContext) -> ApprovalResolution:
        assert context.run_id == "run_sdk_approve"
        assert context.workspace == tmp_path.resolve()
        return ApprovalResolution(request.approval_id, "approved", scope="once", reason="sdk_approved")

    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel(
                [
                    ModelResponse(tool_calls=(ToolCall(name="noop", id="call_approve"),)),
                    ModelResponse(content="done", finish_reason="stop"),
                ]
            ),
            profile=_BasicProfile(),
            tools=[_NoopTool()],
            policy=_ApprovalPolicy(),
            approval_mode="on-request",
            approval_handler=approve,
        )
        assert agent.supports("approvals") is True
        return await agent.run_once("approval", run_id="run_sdk_approve")

    result = asyncio.run(run())

    assert result.status == "completed"
    assert any(event.type == "tool.execution.completed" for event in result.events)
    resolved = next(event for event in result.events if event.type == "approval.resolved")
    assert resolved.data["decision"] == "approved"
    assert resolved.data["reason"] == "sdk_approved"


def test_sdk_async_callable_object_approval_callback_approves_tool(tmp_path) -> None:
    class Approve:
        async def __call__(self, request: ApprovalRequest, context: ApprovalContext) -> ApprovalResolution:
            assert context.run_id == "run_sdk_callable_approve"
            return ApprovalResolution(request.approval_id, "approved", reason="callable_approved")

    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel(
                [
                    ModelResponse(tool_calls=(ToolCall(name="noop", id="call_callable"),)),
                    ModelResponse(content="done", finish_reason="stop"),
                ]
            ),
            profile=_BasicProfile(),
            tools=[_NoopTool()],
            policy=_ApprovalPolicy(),
            approval_mode="on-request",
            approval_handler=Approve(),
        )
        return await agent.run_once("approval", run_id="run_sdk_callable_approve")

    result = asyncio.run(run())

    assert result.status == "completed"
    resolved = next(event for event in result.events if event.type == "approval.resolved")
    assert resolved.data["decision"] == "approved"
    assert resolved.data["reason"] == "callable_approved"


def test_sdk_sync_wrapper_returning_awaitable_approval_callback_approves_tool(tmp_path) -> None:
    def approve(request: ApprovalRequest, context: ApprovalContext):
        async def inner() -> ApprovalResolution:
            assert context.run_id == "run_sdk_awaitable_approve"
            return ApprovalResolution(request.approval_id, "approved", reason="awaitable_approved")

        return inner()

    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel(
                [
                    ModelResponse(tool_calls=(ToolCall(name="noop", id="call_awaitable"),)),
                    ModelResponse(content="done", finish_reason="stop"),
                ]
            ),
            profile=_BasicProfile(),
            tools=[_NoopTool()],
            policy=_ApprovalPolicy(),
            approval_mode="on-request",
            approval_handler=approve,
        )
        return await agent.run_once("approval", run_id="run_sdk_awaitable_approve")

    result = asyncio.run(run())

    assert result.status == "completed"
    resolved = next(event for event in result.events if event.type == "approval.resolved")
    assert resolved.data["decision"] == "approved"
    assert resolved.data["reason"] == "awaitable_approved"


def test_sdk_approval_callback_error_denies_and_closes_wait_step(tmp_path) -> None:
    async def explode(request: ApprovalRequest, context: ApprovalContext) -> ApprovalResolution:
        del request, context
        raise RuntimeError("approval broke")

    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel(
                [
                    ModelResponse(tool_calls=(ToolCall(name="noop", id="call_error"),)),
                    ModelResponse(content="done", finish_reason="stop"),
                ]
            ),
            profile=_BasicProfile(),
            tools=[_NoopTool()],
            policy=_ApprovalPolicy(),
            approval_mode="on-request",
            approval_handler=explode,
        )
        return await agent.run_once("approval", run_id="run_sdk_approval_error")

    result = asyncio.run(run())

    assert result.status == "completed"
    assert any(event.type == "step.failed" and event.data.get("step_kind") == "approval_wait" for event in result.events)
    resolved = next(event for event in result.events if event.type == "approval.resolved")
    assert resolved.data["decision"] == "denied"
    assert "approval handler error" in resolved.data["reason"]
    assert any(event.type == "tool.execution.failed" for event in result.events)


def test_sdk_cancel_unblocks_async_approval_callback(tmp_path) -> None:
    approval_started = asyncio.Event()
    approval_unblock = asyncio.Event()

    async def approve(request: ApprovalRequest, context: ApprovalContext) -> ApprovalResolution:
        del context
        approval_started.set()
        await approval_unblock.wait()
        return ApprovalResolution(request.approval_id, "approved", reason="too_late")

    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel([ModelResponse(tool_calls=(ToolCall(name="noop", id="call_cancel"),))]),
            profile=_BasicProfile(),
            tools=[_NoopTool()],
            policy=_ApprovalPolicy(),
            approval_mode="on-request",
            approval_handler=approve,
        )
        handle = await agent.start("approval", run_id="run_sdk_cancel_approval")
        await asyncio.wait_for(approval_started.wait(), timeout=5)
        await handle.cancel("sdk_cancelled")
        return await handle.result()

    result = asyncio.run(run())

    assert result.status == "cancelled"
    assert result.cancel_reason == "sdk_cancelled"
    resolved = next(event for event in result.events if event.type == "approval.resolved")
    assert resolved.data["decision"] == "cancelled"
    assert resolved.data["reason"] == "sdk_cancelled"
    assert any(event.type == "run.cancelled" for event in result.events)


def test_sdk_cancel_stops_running_shell(tmp_path) -> None:
    async def run():
        agent = Agent.create(
            workspace=tmp_path,
            provider=_StaticModel([ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "sleep 5"}, id="call_sleep"),))]),
            profile=_BasicProfile(),
            tools=default_tools(),
            policy=LocalPolicy(config=PolicyConfig(rules=(PolicyRule("bash", "*", "allow"),))),
        )
        handle = await agent.start("sleep", run_id="run_sdk_cancel_shell")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                event = await asyncio.to_thread(handle._sink.get, 0.05)  # noqa: SLF001 - focused cancellation test hook
            except queue.Empty:
                continue
            if event.type == "command.started":
                break
            if event.type in {"run.completed", "run.failed", "run.cancelled"}:
                raise AssertionError(f"run ended before command started: {event.type}")
        else:
            raise AssertionError("command.started was not emitted")
        await handle.cancel("sdk_cancelled")
        return await handle.result()

    result = asyncio.run(run())

    assert result.status == "cancelled"
    assert any(event.type == "command.cancelled" for event in result.events)
    assert any(event.type == "run.cancelled" for event in result.events)
