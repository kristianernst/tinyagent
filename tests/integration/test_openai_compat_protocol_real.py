from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from tinyagent.core.contracts import Tool
from tinyagent.core.events import LIVE_ONLY_EVENT_TYPES, MemoryEventSink, load_events_jsonl
from tinyagent.core.kernel import Kernel
from tinyagent.core.providers.openai_compat import OpenAICompatibleConfig, OpenAICompatibleProvider
from tinyagent.core.state import Message, RunBudgets, RunState, ToolStep, Workspace
from tinyagent.core.tools import default_tools
from tinyagent.evals.runner import run_eval_suite

pytestmark = pytest.mark.integration


class ToolProtocolProfile:
    name = "integration-tool-protocol"

    def __init__(self, visible_tool_names: Sequence[str]) -> None:
        self.visible_tool_names = tuple(visible_tool_names)

    def system_prompt(self) -> str:
        return (
            "You are testing tinyagent's tool-call protocol. "
            "When the task names a tool, call that exact tool with valid JSON arguments. "
            "After the tool result is shown, stop calling tools and give a concise final answer. "
            "Do not use shell unless the task explicitly names shell."
        )

    def build_messages(self, state: RunState) -> Sequence[Message]:
        messages = [
            Message(role="system", content=self.system_prompt()),
            Message(role="user", content=f"Task:\n{state.task}"),
        ]
        if state.tool_steps:
            messages.append(Message(role="user", content=_tool_history(state.tool_steps)))
        return messages

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        return [all_tools[name] for name in self.visible_tool_names if name in all_tools]

    def should_continue(self, state: RunState) -> bool:
        return not state.done

    def should_finish(self, state: RunState) -> bool:
        return False

    def compact(self, state: RunState) -> None:
        return None


def test_live_model_read_file_tool_call_protocol(tmp_path) -> None:
    provider = _provider_or_skip()
    workspace = _workspace(tmp_path)
    (workspace / "hello.txt").write_text("protocol read ok\n")

    state = _run_protocol_task(
        provider,
        workspace,
        tools=("read_file",),
        task='Call read_file exactly once with {"path":"hello.txt"}. Then answer with the file text.',
        run_id="live-protocol-read-file",
    )

    events = load_events_jsonl(state.output_dir / "events.jsonl")
    _assert_successful_tool_protocol(events, tool="read_file")
    read_event = _event(events, "file.read")
    assert read_event.data["path"] == "hello.txt"
    assert "protocol read ok" in _tool_event(events, "tool.execution.completed", "read_file").data["output"]
    assert "protocol read ok" in state.final_output


def test_live_model_streamed_tool_call_protocol(tmp_path) -> None:
    provider = _provider_or_skip()
    workspace = _workspace(tmp_path)
    (workspace / "stream.txt").write_text("protocol stream ok\n")
    sink = MemoryEventSink()

    state = _run_protocol_task(
        provider,
        workspace,
        tools=("read_file",),
        task='Call read_file exactly once with {"path":"stream.txt"}. Then answer with the file text.',
        run_id="live-protocol-streamed-tool-call",
        stream=True,
        event_sink=sink,
    )

    durable_events = load_events_jsonl(state.output_dir / "events.jsonl")
    _assert_successful_tool_protocol(durable_events, tool="read_file")
    assert LIVE_ONLY_EVENT_TYPES.isdisjoint(event.type for event in durable_events)
    assert any(event.type == "model.tool_call.args.delta" for event in sink.events)
    assert any(
        event.type == "model.tool_call.assembly.completed" and event.data.get("tool") == "read_file"
        for event in sink.events
    )


def test_live_model_write_file_protocol_mutates_workspace(tmp_path) -> None:
    provider = _provider_or_skip()
    workspace = _workspace(tmp_path)

    state = _run_protocol_task(
        provider,
        workspace,
        tools=("write_file",),
        task='Call write_file exactly once with {"path":"created.txt","content":"protocol write ok\\n"}. Then answer done.',
        run_id="live-protocol-write-file",
    )

    events = load_events_jsonl(state.output_dir / "events.jsonl")
    _assert_successful_tool_protocol(events, tool="write_file")
    assert (workspace / "created.txt").read_text() == "protocol write ok\n"
    delta = _tool_event(events, "workspace.delta.completed", "write_file")
    assert delta.data["mutated"] is True
    assert "created.txt" in delta.data["paths"]
    assert any(event.type == "diff.snapshot" for event in events)


def test_live_model_failed_tool_result_is_reported_as_protocol_event(tmp_path) -> None:
    provider = _provider_or_skip()
    workspace = _workspace(tmp_path)

    state = _run_protocol_task(
        provider,
        workspace,
        tools=("read_file",),
        task='Call read_file exactly once with {"path":"missing.txt"}. Then answer that the read failed.',
        run_id="live-protocol-failed-tool-result",
    )

    events = load_events_jsonl(state.output_dir / "events.jsonl")
    requested = _tool_event(events, "model.tool_call.assembly.completed", "read_file")
    failed = _tool_event(events, "tool.execution.failed", "read_file")
    assert requested.data["args"]["path"] == "missing.txt"
    assert failed.data["ok"] is False
    assert failed.data["failure_kind"]
    assert "missing.txt" in failed.data["output"]
    assert state.final_output.strip()


def test_live_model_eval_suite_captures_protocol_outputs(tmp_path) -> None:
    provider = _provider_or_skip()
    suite = _write_tool_protocol_suite(tmp_path)

    eval_run = run_eval_suite(
        suite,
        output_dir=tmp_path / "eval-out",
        model_factory=lambda _task: provider,
        profile=ToolProtocolProfile(("read_file",)),
        tools=default_tools(),
        policy=_allow_all_policy(),
        stream=False,
    )

    assert len(eval_run.results) == 1
    assert eval_run.results[0].success is True
    result = json.loads((eval_run.output_dir / "results.jsonl").read_text().splitlines()[0])
    assert result["success"] is True
    assert "eval protocol ok" in Path(result["run_path"], "final.md").read_text()


def _provider_or_skip() -> OpenAICompatibleProvider:
    if os.environ.get("TINYAGENT_RUN_INTEGRATION") != "1":
        pytest.skip("set TINYAGENT_RUN_INTEGRATION=1 to run live endpoint integration tests")
    missing = [
        name
        for name in ("TINYAGENT_MODEL_BASE_URL", "TINYAGENT_MODEL_API_KEY", "TINYAGENT_MODEL_NAME")
        if not os.environ.get(name)
    ]
    if missing:
        pytest.skip(f"missing live endpoint env vars: {', '.join(missing)}")

    config = OpenAICompatibleConfig.from_env()
    extra_body = {"temperature": 0, **config.extra_body}
    return OpenAICompatibleProvider(replace(config, extra_body=extra_body))


def _run_protocol_task(
    provider: OpenAICompatibleProvider,
    workspace: Path,
    *,
    tools: Sequence[str],
    task: str,
    run_id: str,
    stream: bool = False,
    event_sink: MemoryEventSink | None = None,
) -> RunState:
    kernel = Kernel(
        model=provider,
        profile=ToolProtocolProfile(tools),
        tools=default_tools(),
        policy=_allow_all_policy(),
        budgets=RunBudgets(max_turns=4, max_tool_calls=3, max_run_seconds=90),
        stream=stream,
        event_sink=event_sink,
    )
    state = kernel.run(task, workspace=workspace, run_id=run_id)
    assert not state.failed, state.failure_reason
    return state


def _allow_all_policy():
    from tinyagent.core.state import PolicyDecision

    class AllowAllPolicy:
        def evaluate(self, call, state):
            return PolicyDecision.allow("integration protocol test")

    return AllowAllPolicy()


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _tool_history(steps: Sequence[ToolStep]) -> str:
    rendered = ["Tool results so far:"]
    for step in steps:
        rendered.append(
            "\n".join(
                [
                    f"- tool: {step.call.name}",
                    f"  args: {json.dumps(step.call.args, sort_keys=True)}",
                    f"  ok: {json.dumps(step.result.ok)}",
                    f"  output: {step.result.output}",
                ]
            )
        )
    return "\n".join(rendered)


def _assert_successful_tool_protocol(events, *, tool: str) -> None:
    requested = _tool_event(events, "model.tool_call.assembly.completed", tool)
    started = _tool_event(events, "tool.execution.started", tool)
    completed = _tool_event(events, "tool.execution.completed", tool)
    model_completed = _event(events, "model.call.completed")
    assert requested.data["tool"] == tool
    assert started.data["tool_call_id"] == requested.data["tool_call_id"]
    assert completed.data["tool_call_id"] == requested.data["tool_call_id"]
    assert completed.data["ok"] is True
    assert model_completed.data["tool_call_count"] >= 1


def _event(events, event_type: str):
    return next(event for event in events if event.type == event_type)


def _tool_event(events, event_type: str, tool: str):
    return next(event for event in events if event.type == event_type and event.data.get("tool") == tool)


def _write_tool_protocol_suite(tmp_path: Path) -> Path:
    suite = tmp_path / "suite"
    case = suite / "read-file-protocol"
    files = case / "files"
    files.mkdir(parents=True)
    (files / "source.txt").write_text("eval protocol ok\n")
    (files / "validate.py").write_text(
        "from pathlib import Path\n\n"
        "run_dir = Path('../../runs/read-file-protocol')\n"
        "events = (run_dir / 'events.jsonl').read_text()\n"
        "assert 'model.tool_call.assembly.completed' in events\n"
        "assert 'tool.execution.completed' in events\n"
        "assert 'eval protocol ok' in (run_dir / 'final.md').read_text()\n"
    )
    (case / "task.json").write_text(
        json.dumps(
            {
                "id": "read-file-protocol",
                "task": 'Call read_file exactly once with {"path":"source.txt"}. Then answer with the file text.',
                "validation_command": "python3 validate.py",
                "timeout_seconds": 90,
            }
        )
    )
    return suite
