from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tinyagent.core.contracts import Tool
from tinyagent.core.events import load_events_jsonl
from tinyagent.core.kernel import Kernel
from tinyagent.core.policy import default_policy
from tinyagent.core.providers.factory import ProviderSpec, provider_for
from tinyagent.core.state import Message, RunBudgets, RunState

pytestmark = pytest.mark.integration


class NoToolsProfile:
    name = "native-provider-smoke"

    def system_prompt(self) -> str:
        return "Return concise final answers. Do not ask follow-up questions."

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return [
            Message(role="system", content=self.system_prompt()),
            Message(role="user", content=state.task),
        ]

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        del state, all_tools
        return []

    def should_continue(self, state: RunState) -> bool:
        return not state.done

    def should_finish(self, state: RunState) -> bool:
        return False

    def compact(self, state: RunState) -> None:
        del state


@pytest.mark.parametrize(
    "provider_kind",
    ["openai-responses", "open-responses", "anthropic", "gemini"],
)
def test_live_native_provider_text_smoke(provider_kind: str, tmp_path: Path) -> None:
    provider = _provider_or_skip(provider_kind)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    kernel = Kernel(
        model=provider,
        profile=NoToolsProfile(),
        tools=[],
        policy=default_policy(),
        budgets=RunBudgets(max_model_calls=2, max_tool_calls=0, max_run_seconds=90),
        workspace_mode="current",
    )

    state = kernel.run(
        "Return exactly this short phrase: native provider smoke ok",
        workspace=workspace,
        run_id=f"live-{provider_kind}-text-smoke".replace("_", "-"),
    )

    assert not state.failed, state.failure_reason
    assert state.final_output.strip()
    events = load_events_jsonl(state.output_dir / "events.jsonl")
    started = next(event for event in events if event.type == "run.started")
    assert started.data["provider"] == provider_kind
    assert next(event for event in events if event.type == "model.call.completed").data["tool_call_count"] == 0
    assert (state.output_dir / "artifacts" / "model-request-logical-0001.json").exists()
    assert (state.output_dir / "artifacts" / "model-response-0001.json").exists()


def _provider_or_skip(provider_kind: str):
    if os.environ.get("TINYAGENT_RUN_INTEGRATION") != "1":
        pytest.skip("set TINYAGENT_RUN_INTEGRATION=1 to run live endpoint integration tests")
    selected = os.environ.get("TINYAGENT_INTEGRATION_PROVIDER")
    if selected != provider_kind:
        pytest.skip(f"set TINYAGENT_INTEGRATION_PROVIDER={provider_kind} to run this provider smoke")
    missing = _missing_env(provider_kind)
    if missing:
        pytest.skip(f"missing live endpoint env vars for {provider_kind}: {', '.join(missing)}")
    return provider_for(ProviderSpec(kind=provider_kind), "native provider smoke")


def _missing_env(provider_kind: str) -> list[str]:
    required = ["TINYAGENT_MODEL_NAME"]
    if provider_kind == "open-responses":
        required.append("TINYAGENT_MODEL_BASE_URL")
    else:
        required.append("TINYAGENT_MODEL_API_KEY")
    return [name for name in required if not os.environ.get(name)]
