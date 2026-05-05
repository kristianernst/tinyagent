from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agentd.contracts import Tool
from agentd.kernel import Kernel
from agentd.model_stream import ModelDelta, assemble_model_deltas, parse_chat_completion_chunk
from agentd.models import (
    FakeModelProvider,
    ModelCapabilities,
    ModelSpec,
    ProviderError,
)
from agentd.policy import default_policy
from agentd.profiles import ApexCoderProfile
from agentd.providers.openai_compat import OpenAICompatibleConfig, OpenAICompatibleProvider
from agentd.state import Message, ModelResponse, PolicyDecision, RunBudgets, RunState, ToolCall, ToolResult, Workspace
from agentd.tools import default_tools


class SampleTool:
    name = "sample_tool"
    schema = {
        "name": "sample_tool",
        "description": "Sample tool.",
        "parameters": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    }

    def run(self, call: ToolCall, state: RunState) -> ToolResult:
        return ToolResult(tool_name=self.name, output=call.args["value"])


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


class StreamingOpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, raw_chunks: list[dict]) -> None:
        super().__init__(
            OpenAICompatibleConfig(
                base_url="https://models.example.test/v1",
                api_key="test-key",
                model="test-model",
            )
        )
        self.payloads: list[dict] = []
        self.raw_chunks = raw_chunks

    def _post_stream(self, payload: dict):
        self.payloads.append(payload)
        yield from self.raw_chunks


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


def test_fake_provider_stream_assembles_same_final_response() -> None:
    call = ToolCall(id="call_1", name="sample_tool", args={"value": "done"})
    provider = FakeModelProvider(
        [
            ModelResponse(
                content="thinking",
                tool_calls=(call,),
                finish_reason="tool_calls",
                raw={"usage": {"total_tokens": 12}},
            )
        ]
    )

    response = assemble_model_deltas(provider.name, provider.stream([], [], _state_stub()))

    assert response.content == "thinking"
    assert response.tool_calls == (call,)
    assert response.finish_reason == "tool_calls"
    assert response.raw["usage"] == {"total_tokens": 12}


def test_openai_compatible_config_reads_environment() -> None:
    config = OpenAICompatibleConfig.from_env(
        {
            "TINYAGENT_MODEL_BASE_URL": "https://models.example.test/v1",
            "TINYAGENT_MODEL_API_KEY": "key",
            "TINYAGENT_MODEL_NAME": "model",
            "TINYAGENT_MODEL_TIMEOUT_SECONDS": "12",
            "TINYAGENT_MODEL_CONTEXT_WINDOW": "64000",
            "TINYAGENT_MODEL_MAX_OUTPUT_TOKENS": "4000",
            "TINYAGENT_MODEL_REASONING_JSON": '{"effort":"medium","budget_tokens":1024}',
            "TINYAGENT_MODEL_EXTRA_BODY_JSON": '{"max_tokens":128,"temperature":0}',
        }
    )

    assert config.base_url == "https://models.example.test/v1"
    assert config.api_key == "key"
    assert config.model == "model"
    assert config.timeout_seconds == 12
    assert config.context_window == 64_000
    assert config.max_output_tokens == 4_000
    assert config.reasoning == {"effort": "medium", "budget_tokens": 1024}
    assert config.extra_body == {"max_tokens": 128, "temperature": 0}


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


def test_openai_compatible_config_validates_extra_body_json() -> None:
    base_env = {
        "TINYAGENT_MODEL_API_KEY": "key",
        "TINYAGENT_MODEL_NAME": "model",
    }

    with pytest.raises(ProviderError, match="valid JSON"):
        OpenAICompatibleConfig.from_env({**base_env, "TINYAGENT_MODEL_EXTRA_BODY_JSON": "{"})

    with pytest.raises(ProviderError, match="JSON object"):
        OpenAICompatibleConfig.from_env({**base_env, "TINYAGENT_MODEL_EXTRA_BODY_JSON": "[]"})

    with pytest.raises(ProviderError, match="protected keys: messages"):
        OpenAICompatibleConfig.from_env({**base_env, "TINYAGENT_MODEL_EXTRA_BODY_JSON": '{"messages":[]}'})


def test_openai_compatible_config_validates_reasoning_json() -> None:
    base_env = {
        "TINYAGENT_MODEL_API_KEY": "key",
        "TINYAGENT_MODEL_NAME": "model",
    }

    with pytest.raises(ProviderError, match="valid JSON"):
        OpenAICompatibleConfig.from_env({**base_env, "TINYAGENT_MODEL_REASONING_JSON": "{"})

    with pytest.raises(ProviderError, match="JSON object"):
        OpenAICompatibleConfig.from_env({**base_env, "TINYAGENT_MODEL_REASONING_JSON": "true"})


def test_openai_compatible_provider_merges_extra_body_without_overriding_stream_semantics() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            base_url="https://models.example.test/v1",
            api_key="test-key",
            model="test-model",
            reasoning={"effort": "low", "budget_tokens": 1024},
            extra_body={"max_tokens": 128, "temperature": 0, "stream_options": {"debug": True}},
        )
    )

    payload = provider.build_stream_payload([Message(role="user", content="hello")], [SampleTool()], _state_stub())

    assert payload["model"] == "test-model"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert payload["tools"] == [{"type": "function", "function": SampleTool.schema}]
    assert payload["max_tokens"] == 128
    assert payload["temperature"] == 0
    assert payload["reasoning"] == {"effort": "low", "budget_tokens": 1024}
    assert payload["thinking_budget_tokens"] == 1024
    assert payload["stream"] is True
    assert payload["stream_options"] == {"debug": True, "include_usage": True}
    assert provider.capabilities.tool_protocol == "chat_completions"
    assert provider.capabilities.input_budget_tokens == 120_000


def test_openai_compatible_provider_preserves_explicit_thinking_budget_tokens() -> None:
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            base_url="https://models.example.test/v1",
            api_key="test-key",
            model="test-model",
            reasoning={"budget_tokens": 1024},
            extra_body={"thinking_budget_tokens": 256},
        )
    )

    payload = provider.build_payload([Message(role="user", content="hello")], [], _state_stub())

    assert payload["reasoning"] == {"budget_tokens": 1024}
    assert payload["thinking_budget_tokens"] == 256


def test_kernel_fails_clearly_when_provider_does_not_support_tools(tmp_path) -> None:
    class TextOnlyProvider:
        name = "text-only"
        capabilities = ModelCapabilities(supports_tools=False, tool_protocol="none")

        def complete(self, messages, tools, state):
            raise AssertionError("kernel should reject visible tools before calling provider")

    state = Kernel(
        model=TextOnlyProvider(),
        profile=BasicProfile(),
        tools=[SampleTool()],
        policy=AllowAllPolicy(),
        workspace_mode="current",
    ).run("use tools", workspace=tmp_path)

    assert state.failed is True
    assert state.failure_reason == "Model provider does not support tools."
    failed = next(event for event in state.events if event.type == "model.call.failed")
    assert failed.data["capabilities"]["supports_tools"] is False


def test_model_spec_drives_context_budget_and_visible_tools(tmp_path) -> None:
    class ClaudeLikeProvider:
        name = "claude-like"
        model_spec = ModelSpec(
            provider="anthropic",
            model="claude-test",
            protocol="anthropic",
            edit_style="str_replace",
            capabilities=ModelCapabilities(context_window=20_000, max_output_tokens=2_000),
        )

        def __init__(self) -> None:
            self.tools = []

        def complete(self, messages, tools, state):
            del messages, state
            self.tools = [tool.name for tool in tools]
            return ModelResponse(content="done", finish_reason="stop")

    provider = ClaudeLikeProvider()
    state = Kernel(
        model=provider,
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=default_policy(),
        workspace_mode="current",
    ).run("use spec", workspace=tmp_path, run_id="run_model_spec")

    assert state.failed is False
    assert provider.tools == ["read_file", "read_context", "search_repo", "str_replace_edit", "shell"]
    assert state.model_spec["edit_style"] == "str_replace"
    report_event = next(event for event in state.events if event.type == "context.report.written")
    report = json.loads((state.output_dir / report_event.data["context_report_artifact"]).read_text())
    assert report["budget"] == 18_000
    assert state.context_token_estimate <= 18_000


def test_model_spec_hidden_edit_tool_is_blocked(tmp_path) -> None:
    class ClaudeLikeProvider:
        name = "claude-like"
        model_spec = ModelSpec(provider="anthropic", model="claude-test", protocol="anthropic", edit_style="str_replace")

        def complete(self, messages, tools, state):
            del messages, tools, state
            return ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": "*** Begin Patch\n*** End Patch"}),))

    state = Kernel(
        model=ClaudeLikeProvider(),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=AllowAllPolicy(),
        workspace_mode="current",
        budgets=RunBudgets(max_turns=1),
    ).run("try hidden apply_patch", workspace=tmp_path, run_id="run_hidden_edit_spec")

    result = state.tool_results[0]
    assert result.ok is False
    assert result.output == "Tool is not visible for this profile: apply_patch"
    assert "str_replace_edit" in result.data["visible_tools"]
    assert "apply_patch" not in result.data["visible_tools"]


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
                                    "name": "sample_tool",
                                    "arguments": json.dumps({"value": "done"}),
                                },
                            }
                        ],
                    },
                }
            ]
        }
    )

    response = provider.complete(
        [Message(role="user", content="use the sample tool")],
        [SampleTool()],
        _state_stub(),
    )

    assert provider.payloads == [
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": "use the sample tool"}],
            "tools": [{"type": "function", "function": SampleTool.schema}],
        }
    ]
    assert response.content == ""
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls == (ToolCall(id="call_1", name="sample_tool", args={"value": "done"}),)


def test_openai_compatible_provider_streams_text_tool_args_and_usage() -> None:
    provider = StreamingOpenAIProvider(
        [
            {
                "id": "chatcmpl_1",
                "choices": [{"delta": {"content": "Working "}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl_1",
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "sample_tool"},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl_1",
                "choices": [
                    {
                        "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"value":'}}]},
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl_1",
                "choices": [
                    {
                        "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"done"}'}}]},
                        "finish_reason": "tool_calls",
                    }
                ],
            },
            {"id": "chatcmpl_1", "choices": [], "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}},
        ]
    )

    response = assemble_model_deltas(
        provider.name,
        provider.stream([Message(role="user", content="use tool")], [SampleTool()], _state_stub()),
    )

    assert provider.payloads == [
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": "use tool"}],
            "tools": [{"type": "function", "function": SampleTool.schema}],
            "stream": True,
            "stream_options": {"include_usage": True},
        }
    ]
    assert response.content == "Working "
    assert response.tool_calls == (ToolCall(id="call_1", name="sample_tool", args={"value": "done"}),)
    assert response.finish_reason == "tool_calls"
    assert response.raw["usage"] == {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}


def test_chat_completion_chunk_maps_llamacpp_reasoning_content_to_visible_reasoning_delta() -> None:
    deltas = list(
        parse_chat_completion_chunk(
            {
                "id": "chunk_1",
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "raw reasoning",
                            "content": "answer",
                        },
                        "finish_reason": "stop",
                    }
                ],
            }
        )
    )

    assert deltas[0].kind == "text_delta"
    assert deltas[1].kind == "reasoning_visible_delta"
    assert deltas[1].delta == "raw reasoning"
    assert deltas[1].data["provider_field"] == "reasoning_content"
    assert assemble_model_deltas("openai-compatible", deltas).content == "answer"


def test_stream_assembler_rejects_invalid_partial_tool_arguments() -> None:
    deltas = [
        ModelDelta(kind="tool_call_started", tool_call_id="call_1", data={"id": "call_1", "name": "sample_tool"}),
        ModelDelta(kind="tool_call_args_delta", tool_call_id="call_1", delta="[]"),
        ModelDelta(kind="completed", data={"finish_reason": "tool_calls"}),
    ]

    with pytest.raises(ProviderError, match="must be a JSON object"):
        assemble_model_deltas("test", deltas)


def test_openai_compatible_provider_does_not_send_message_meta() -> None:
    provider = RecordingOpenAIProvider(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "done"},
                }
            ]
        }
    )

    provider.complete(
        [Message(role="user", content="hello", meta={"context_layer": "task", "name": "ignored"})],
        [],
        _state_stub(),
    )

    assert provider.payloads[0]["messages"] == [{"role": "user", "content": "hello"}]


def test_kernel_writes_exact_openai_compatible_payload_artifact(tmp_path) -> None:
    provider = RecordingOpenAIProvider(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": "done"},
                }
            ]
        }
    )
    kernel = Kernel(
        model=provider,
        profile=BasicProfile(),
        tools=[SampleTool()],
        policy=AllowAllPolicy(),
    )

    state = kernel.run("write payload artifact", workspace=tmp_path)

    request = next(event for event in state.events if event.type == "model.call.started")
    assert request.data["logical_request_artifact"] == "artifacts/model-request-logical-0001.json"
    assert request.data["http_request_artifact"] == "artifacts/model-request-http-0001.json"
    payload = json.loads((state.output_dir / request.data["http_request_artifact"]).read_text())
    assert payload == provider.payloads[0]
    assert payload["model"] == "test-model"


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
                                    "name": "sample_tool",
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

    assert response.tool_calls[0].name == "sample_tool"
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
                                    "name": "sample_tool",
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
        tools=[SampleTool()],
        policy=AllowAllPolicy(),
    )

    state = kernel.run("provider failure", workspace=tmp_path)

    assert state.failed is True
    assert state.failure_reason == "Model provider error: FakeModelProvider has no response left."
    assert [event.type for event in state.events][-1] == "run.failed"


def _state_stub() -> RunState:
    return RunState.create("test", workspace=Workspace(Path(".")))
