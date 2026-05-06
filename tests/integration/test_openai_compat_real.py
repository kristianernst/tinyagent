from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tinyagent.core.contracts import Tool
from tinyagent.evals.runner import run_eval_suite
from tinyagent.core.events import LIVE_ONLY_EVENT_TYPES, MemoryEventSink, load_events_jsonl
from tinyagent.core.kernel import Kernel
from tinyagent.core.model_stream import assemble_model_deltas
from tinyagent.core.policy import default_policy
from tinyagent.core.providers.openai_compat import OpenAICompatibleProvider
from tinyagent.core.state import Message, RunState, Workspace

pytestmark = pytest.mark.integration


class NoToolsProfile:
    name = "integration-no-tools"

    def system_prompt(self) -> str:
        return "Return concise final answers. Do not ask follow-up questions."

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return [
            Message(role="system", content=self.system_prompt()),
            Message(role="user", content=state.task),
        ]

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        return []

    def should_continue(self, state: RunState) -> bool:
        return True

    def should_finish(self, state: RunState) -> bool:
        return False

    def compact(self, state: RunState) -> None:
        return None


def test_real_openai_compatible_provider_streams_to_model_response(tmp_path) -> None:
    provider = _provider_or_skip()
    state = RunState.create("integration stream", Workspace(_workspace(tmp_path)), run_id="provider-stream")
    messages = [
        Message(role="system", content="Return only a short final answer."),
        Message(role="user", content="Return: stream ok"),
    ]

    deltas = list(provider.stream(messages, [], state))
    response = assemble_model_deltas(provider.name, deltas)

    assert any(delta.kind in {"text_delta", "reasoning_summary_delta", "reasoning_visible_delta"} for delta in deltas)
    assert response.raw["streamed"] is True
    assert response.finish_reason in {"stop", "length"}
    if response.finish_reason != "length":
        assert response.content.strip()


def test_real_openai_compatible_kernel_stream_trace(tmp_path) -> None:
    provider = _provider_or_skip()
    sink = MemoryEventSink()
    kernel = Kernel(
        model=provider,
        profile=NoToolsProfile(),
        tools=[],
        policy=default_policy(),
        stream=True,
        event_sink=sink,
    )

    state = kernel.run(
        "Return a short final answer: stream ok",
        workspace=_workspace(tmp_path),
        run_id="real-stream-smoke",
    )

    assert state.turn_count == 1
    live_types = [event.type for event in sink.events]
    assert "model.stream.started" in live_types
    assert "model.completed" in live_types
    assert any(event.type in {"model.text.delta", "reasoning.summary.delta", "reasoning.visible.delta"} for event in sink.events)
    durable_types = [event.type for event in load_events_jsonl(state.output_dir / "events.jsonl")]
    assert LIVE_ONLY_EVENT_TYPES.isdisjoint(durable_types)
    assert (state.output_dir / "artifacts" / "model-response-0001.json").exists()
    assert (state.output_dir / "final.md").read_text().startswith("# Final output\n\n")
    assert durable_types[-1] in {"run.completed", "run.failed"}
    if state.failed:
        assert state.failure_reason
    else:
        assert state.final_output.strip()


def test_real_openai_compatible_eval_smoke(tmp_path) -> None:
    provider = _provider_or_skip()
    suite = _write_no_tools_suite(tmp_path)

    eval_run = run_eval_suite(
        suite,
        output_dir=tmp_path / "eval-out",
        model_factory=lambda _task: provider,
        profile=NoToolsProfile(),
        tools=[],
        policy=default_policy(),
        stream=True,
    )

    assert len(eval_run.results) == 1
    assert eval_run.results[0].success is True
    assert (eval_run.output_dir / "results.jsonl").exists()
    assert (eval_run.output_dir / "report.md").exists()


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
    return OpenAICompatibleProvider.from_env()


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


def _write_no_tools_suite(tmp_path: Path) -> Path:
    suite = tmp_path / "suite"
    case = suite / "direct-answer"
    files = case / "files"
    files.mkdir(parents=True)
    (files / "validate.py").write_text("from pathlib import Path\n\nassert Path('marker.txt').read_text() == 'ok\\n'\n")
    (files / "marker.txt").write_text("ok\n")
    (case / "task.json").write_text(
        json.dumps(
            {
                "id": "direct-answer",
                "task": "Return a short final answer: eval ok",
                "validation_command": "python3 validate.py",
                "timeout_seconds": 60,
            }
        )
    )
    return suite
