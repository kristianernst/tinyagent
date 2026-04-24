from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agentd.contracts import Tool
from agentd.kernel import Kernel
from agentd.models import FakeModelProvider, OpenAICompatibleConfig, OpenAICompatibleProvider, ProviderError
from agentd.state import Message, ModelResponse, PolicyDecision, RunState, ToolCall, ToolResult, Workspace


class FinishTool:
    name = "finish"
    schema = {
        "name": "finish",
        "description": "Finish the run.",
        "parameters": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        return ToolResult(tool_name=self.name, output=call.args["summary"], finish=True)


class AllowAllPolicy:
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        return PolicyDecision.allow()


class BasicProfile:
    name = "test-profile"

    def system_prompt(self) -> str:
        return "system"

    def build_messages(self, state: RunState) -> Sequence[Message]:
        return [Message(role="user", content=state.task)]

    def visible_tools(self, state: RunState, all_tools: Mapping[str, Tool]) -> Sequence[Tool]:
        return list(all_tools.values())

    def should_continue(self, state: RunState) -> bool:
        return True

    def should_finish(self, state: RunState) -> bool:
        return False

    def compact(self, state: RunState) -> None:
        return None


class RecordingOpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, raw_response: dict) -> None:
        super().__init__(
            OpenAICompatibleConfig(
                base_url="https://models.example.test/v1",
                api_key="test-key",
                model="test-model",
            )
        )
        self.payloads: list[dict] = []
        self.raw_response = raw_response

    def _post(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return self.raw_response


def test_fake_provider_returns_responses_in_order() -> None:
    provider = FakeModelProvider(
        [
            ModelResponse(content="first"),
            ModelResponse(content="second"),
        ]
    )

    assert provider.complete([], [], _state_stub()).content == "first"
    assert provider.complete([], [], _state_stub()).content == "second"

    with pytest.raises(ProviderError, match="no response left"):
        provider.complete([], [], _state_stub())


def test_openai_compatible_config_reads_environment() -> None:
    config = OpenAICompatibleConfig.from_env(
        {
            "TINYAGENT_MODEL_BASE_URL": "https://models.example.test/v1",
            "TINYAGENT_MODEL_API_KEY": "key",
            "TINYAGENT_MODEL_NAME": "model",
            "TINYAGENT_MODEL_TIMEOUT_SECONDS": "12",
        }
    )

    assert config.base_url == "https://models.example.test/v1"
    assert config.api_key == "key"
    assert config.model == "model"
    assert config.timeout_seconds == 12


def test_openai_compatible_config_requires_key_and_model() -> None:
    with pytest.raises(ProviderError, match="TINYAGENT_MODEL_API_KEY"):
        OpenAICompatibleConfig.from_env({})

    with pytest.raises(ProviderError, match="TINYAGENT_MODEL_NAME"):
        OpenAICompatibleConfig.from_env({"TINYAGENT_MODEL_API_KEY": "key"})

    with pytest.raises(ProviderError, match="TIMEOUT_SECONDS"):
        OpenAICompatibleConfig.from_env(
            {
                "TINYAGENT_MODEL_API_KEY": "key",
                "TINYAGENT_MODEL_NAME": "model",
                "TINYAGENT_MODEL_TIMEOUT_SECONDS": "soon",
            }
        )


def test_openai_compatible_provider_sends_messages_tools_and_parses_tool_calls() -> None:
    provider = RecordingOpenAIProvider(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "finish",
                                    "arguments": json.dumps({"summary": "done"}),
                                },
                            }
                        ],
                    },
                }
            ]
        }
    )

    response = provider.complete(
        [Message(role="user", content="finish")],
        [FinishTool()],
        _state_stub(),
    )

    assert provider.payloads == [
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": "finish"}],
            "tools": [{"type": "function", "function": FinishTool.schema}],
        }
    ]
    assert response.content == ""
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls == [ToolCall(id="call_1", name="finish", args={"summary": "done"})]


def test_openai_compatible_provider_generates_tool_call_id_when_provider_omits_id() -> None:
    provider = RecordingOpenAIProvider(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "type": "function",
                                "function": {
                                    "name": "finish",
                                    "arguments": "{}",
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )

    response = provider.complete([], [], _state_stub())

    assert response.tool_calls[0].name == "finish"
    assert response.tool_calls[0].args == {}
    assert response.tool_calls[0].id.startswith("call_")


def test_openai_compatible_provider_rejects_invalid_tool_arguments() -> None:
    provider = RecordingOpenAIProvider(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "finish",
                                    "arguments": "[]",
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )

    with pytest.raises(ProviderError, match="must be a JSON object"):
        provider.complete([], [], _state_stub())


def test_openai_compatible_provider_requires_tool_call_name() -> None:
    provider = RecordingOpenAIProvider(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {"arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        }
    )

    with pytest.raises(ProviderError, match="function.name"):
        provider.complete([], [], _state_stub())


def test_kernel_surfaces_provider_errors_as_run_failures(tmp_path) -> None:
    kernel = Kernel(
        model=FakeModelProvider([]),
        profile=BasicProfile(),
        tools=[FinishTool()],
        policy=AllowAllPolicy(),
    )

    state = kernel.run("finish", workspace=tmp_path)

    assert state.failed is True
    assert state.failure_reason == "Model provider error: FakeModelProvider has no response left."
    assert [event.type for event in state.events][-1] == "RunFailed"


def _state_stub() -> RunState:
    return RunState.create("test", workspace=Workspace(Path(".")))
