from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from tinyagent.core.contracts import Tool
from tinyagent.core.kernel import Kernel
from tinyagent.core.model_stream import ModelDelta, assemble_model_deltas, parse_chat_completion_chunk
from tinyagent.core.models import (
    FakeModelProvider,
    ModelCapabilities,
    ModelSpec,
    ProviderError,
)
from tinyagent.core.policy import default_policy
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.providers.factory import ProviderRegistry, ProviderSpec, provider_for
from tinyagent.core.providers.anthropic import AnthropicMessagesConfig, AnthropicMessagesProvider, parse_message
from tinyagent.core.providers.gemini import (
    GeminiGenerateContentConfig,
    GeminiGenerateContentProvider,
    parse_generate_content,
)
from tinyagent.core.providers.openai_compat import OpenAICompatibleConfig, OpenAICompatibleProvider
from tinyagent.core.providers.openai_responses import (
    OpenAIResponsesConfig,
    OpenAIResponsesProvider,
    parse_response_stream_event,
)
from tinyagent.core.state import (
    Message,
    ModelRequestContext,
    ModelResponse,
    PolicyDecision,
    RunBudgets,
    RunState,
    ToolCall,
    ToolResult,
    ToolStep,
    Workspace,
)
from tinyagent.core.tools import default_tools


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


class RecordingResponsesProvider(OpenAIResponsesProvider):
    def __init__(self, raw_response: dict, config: OpenAIResponsesConfig | None = None) -> None:
        super().__init__(
            config
            or OpenAIResponsesConfig(
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


class StreamingResponsesProvider(OpenAIResponsesProvider):
    def __init__(self, raw_events: list[dict]) -> None:
        super().__init__(
            OpenAIResponsesConfig(
                base_url="https://models.example.test/v1",
                api_key="test-key",
                model="test-model",
            )
        )
        self.payloads: list[dict] = []
        self.raw_events = raw_events

    def _post_stream(self, payload: dict):
        self.payloads.append(payload)
        yield from self.raw_events


class RecordingOpenResponsesProvider(OpenAIResponsesProvider):
    def __init__(self, raw_response: dict, config: OpenAIResponsesConfig | None = None) -> None:
        super().__init__(
            config
            or OpenAIResponsesConfig(
                base_url="http://127.0.0.1:11434/v1",
                api_key="",
                model="test-model",
                protocol="open_responses",
                send_store=False,
                send_prompt_cache_key=False,
                supports_prompt_cache_key=False,
                supports_reasoning=False,
            ),
            name="open-responses",
            adapter="tinyagent.open_responses.v1",
        )
        self.payloads: list[dict] = []
        self.raw_response = raw_response

    def _post(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return self.raw_response


class RecordingAnthropicProvider(AnthropicMessagesProvider):
    def __init__(self, raw_response: dict, config: AnthropicMessagesConfig | None = None) -> None:
        super().__init__(
            config
            or AnthropicMessagesConfig(
                base_url="https://api.anthropic.test/v1",
                api_key="test-key",
                model="claude-test",
            )
        )
        self.payloads: list[dict] = []
        self.raw_response = raw_response

    def _post(self, payload: dict) -> dict:
        self.payloads.append(payload)
        return self.raw_response


class RecordingGeminiProvider(GeminiGenerateContentProvider):
    def __init__(self, raw_response: dict, config: GeminiGenerateContentConfig | None = None) -> None:
        super().__init__(
            config
            or GeminiGenerateContentConfig(
                base_url="https://generativelanguage.googleapis.com/v1beta",
                api_key="test-key",
                model="gemini-test",
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


def test_provider_registry_can_create_registered_provider() -> None:
    class CustomFactory:
        kind = "custom"

        def create(self, spec, task, env=None):
            del env
            return FakeModelProvider([ModelResponse(content=f"{spec.model}:{task}")], model=spec.model or "custom")

    registry = ProviderRegistry()
    registry.register(CustomFactory())

    provider = registry.create(ProviderSpec(kind="custom", model="m"), "task")

    assert registry.kinds() == ("custom",)
    assert provider.complete([], [], _state_stub()).content == "m:task"


def test_default_provider_factory_records_adapter_metadata() -> None:
    provider = provider_for(ProviderSpec(kind="fake", model="fake-model"), "task")

    assert provider.model == "fake-model"
    assert provider.adapter == "tinyagent.fake.v1"


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

    payload = provider.build_stream_payload([Message(role="user", content="hello")], [SampleTool()], _request_stub())

    assert payload["model"] == "test-model"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert payload["tools"] == [{"type": "function", "function": SampleTool.schema}]
    assert payload["max_tokens"] == 128
    assert payload["temperature"] == 0
    assert payload["reasoning"] == {"effort": "low", "budget_tokens": 1024}
    assert payload["thinking_budget_tokens"] == 1024
    assert payload["stream"] is True
    assert payload["stream_options"] == {"debug": True, "include_usage": True}
    assert provider.capabilities.protocol == "openai_chat_completions"
    assert provider.capabilities.tool_result_mode == "chat_tool_messages"
    assert provider.capabilities.input_budget_tokens == 120_000
    assert provider.model_spec.to_json_dict()["adapter"] == "tinyagent.openai_compat.v1"


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

    payload = provider.build_payload([Message(role="user", content="hello")], [], _request_stub())

    assert payload["reasoning"] == {"budget_tokens": 1024}
    assert payload["thinking_budget_tokens"] == 256


def test_anthropic_messages_config_reads_environment() -> None:
    config = AnthropicMessagesConfig.from_env(
        {
            "TINYAGENT_MODEL_BASE_URL": "https://api.anthropic.test/v1",
            "TINYAGENT_MODEL_API_KEY": "key",
            "TINYAGENT_MODEL_NAME": "claude-test",
            "TINYAGENT_MODEL_TIMEOUT_SECONDS": "12",
            "TINYAGENT_MODEL_CONTEXT_WINDOW": "200000",
            "TINYAGENT_MODEL_MAX_OUTPUT_TOKENS": "4096",
            "TINYAGENT_ANTHROPIC_VERSION": "2023-06-01",
            "TINYAGENT_MODEL_EXTRA_BODY_JSON": '{"temperature":0}',
        }
    )

    assert config.base_url == "https://api.anthropic.test/v1"
    assert config.api_key == "key"
    assert config.model == "claude-test"
    assert config.timeout_seconds == 12
    assert config.context_window == 200_000
    assert config.max_output_tokens == 4_096
    assert config.anthropic_version == "2023-06-01"
    assert config.extra_body == {"temperature": 0}


def test_anthropic_messages_provider_sends_native_payload_and_parses_tool_use() -> None:
    provider = RecordingAnthropicProvider(
        {
            "id": "msg_123",
            "type": "message",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Working."},
                {"type": "tool_use", "id": "toolu_1", "name": "sample_tool", "input": {"value": "done"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 3, "cache_read_input_tokens": 2, "output_tokens": 4},
        }
    )

    response = provider.complete(
        [
            Message(role="system", content="system instructions"),
            Message(role="user", content="use the sample tool"),
        ],
        [SampleTool()],
        _request_stub(),
    )

    assert provider.payloads == [
        {
            "model": "claude-test",
            "max_tokens": 8000,
            "messages": [{"role": "user", "content": "use the sample tool"}],
            "system": "system instructions",
            "tools": [
                {
                    "name": "sample_tool",
                    "description": "Sample tool.",
                    "input_schema": SampleTool.schema["parameters"],
                }
            ],
        }
    ]
    assert response.content == "Working."
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls == (ToolCall(id="toolu_1", name="sample_tool", args={"value": "done"}),)
    assert response.raw["usage"] == {
        "input_tokens": 3,
        "cached_input_tokens": 2,
        "output_tokens": 4,
        "total_tokens": 7,
    }
    assert provider.capabilities.protocol == "anthropic_messages"
    assert provider.capabilities.tool_result_mode == "anthropic_blocks"
    assert provider.model_spec.to_json_dict()["adapter"] == "tinyagent.anthropic_messages.v1"
    assert provider.model_spec.edit_style == "str_replace"


def test_anthropic_messages_provider_sends_native_tool_result_history() -> None:
    provider = AnthropicMessagesProvider(
        AnthropicMessagesConfig(
            base_url="https://api.anthropic.test/v1",
            api_key="test-key",
            model="claude-test",
        )
    )
    state = _state_stub()
    state.tool_steps.append(
        ToolStep(
            call=ToolCall(id="toolu_read", name="read_file", args={"path": "hello.txt"}),
            result=ToolResult(tool_name="read_file", call_id="toolu_read", output="hello.txt\n1: hello", ok=True),
        )
    )

    payload = provider.build_payload([Message(role="user", content="continue")], [SampleTool()], _request_stub(state))

    assert payload["messages"] == [
        {"role": "user", "content": "continue"},
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "toolu_read", "name": "read_file", "input": {"path": "hello.txt"}}],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_read",
                    "content": "hello.txt\n1: hello",
                    "is_error": False,
                }
            ],
        },
    ]


def test_anthropic_provider_factory_uses_shared_model_env() -> None:
    provider = provider_for(
        ProviderSpec(kind="anthropic", model="claude-test"),
        "task",
        env={"TINYAGENT_MODEL_API_KEY": "key"},
    )

    assert isinstance(provider, AnthropicMessagesProvider)
    assert provider.model == "claude-test"
    assert provider.model_spec.protocol == "anthropic_messages"


def test_anthropic_message_parser_rejects_malformed_tool_use() -> None:
    with pytest.raises(ProviderError, match="missing id"):
        parse_message({"content": [{"type": "tool_use", "name": "sample_tool", "input": {}}]})


def test_gemini_generate_content_config_reads_environment() -> None:
    config = GeminiGenerateContentConfig.from_env(
        {
            "TINYAGENT_MODEL_BASE_URL": "https://generativelanguage.googleapis.com/v1",
            "TINYAGENT_MODEL_API_KEY": "key",
            "TINYAGENT_MODEL_NAME": "gemini-3-flash-preview",
            "TINYAGENT_MODEL_TIMEOUT_SECONDS": "13",
            "TINYAGENT_MODEL_CONTEXT_WINDOW": "1048576",
            "TINYAGENT_MODEL_MAX_OUTPUT_TOKENS": "4096",
            "TINYAGENT_GEMINI_GENERATION_CONFIG_JSON": '{"temperature":0}',
            "TINYAGENT_MODEL_EXTRA_BODY_JSON": '{"safetySettings":[]}',
        }
    )

    assert config.base_url == "https://generativelanguage.googleapis.com/v1"
    assert config.api_key == "key"
    assert config.model == "gemini-3-flash-preview"
    assert config.timeout_seconds == 13
    assert config.context_window == 1_048_576
    assert config.max_output_tokens == 4_096
    assert config.generation_config == {"temperature": 0}
    assert config.extra_body == {"safetySettings": []}


def test_gemini_provider_sends_native_payload_and_parses_function_call() -> None:
    provider = RecordingGeminiProvider(
        {
            "responseId": "gemini-response-1",
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {"text": "Working."},
                            {
                                "functionCall": {
                                    "id": "call_gemini",
                                    "name": "sample_tool",
                                    "args": {"value": "done"},
                                },
                                "thoughtSignature": "sig-123",
                            },
                        ],
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 3,
                "candidatesTokenCount": 4,
                "thoughtsTokenCount": 2,
                "totalTokenCount": 9,
            },
        },
        config=GeminiGenerateContentConfig(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="test-key",
            model="gemini-test",
            generation_config={"temperature": 0},
        ),
    )

    response = provider.complete(
        [
            Message(role="system", content="system instructions"),
            Message(role="user", content="use the sample tool"),
        ],
        [SampleTool()],
        _request_stub(),
    )

    assert provider.payloads == [
        {
            "contents": [{"role": "user", "parts": [{"text": "use the sample tool"}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 8000},
            "systemInstruction": {"parts": [{"text": "system instructions"}]},
            "tools": [
                {
                    "functionDeclarations": [
                        {
                            "name": "sample_tool",
                            "description": "Sample tool.",
                            "parameters": SampleTool.schema["parameters"],
                        }
                    ]
                }
            ],
        }
    ]
    assert response.content == "Working."
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls == (ToolCall(id="call_gemini", name="sample_tool", args={"value": "done"}),)
    assert response.tool_calls[0].metadata == {"gemini": {"thoughtSignature": "sig-123"}}
    assert response.raw["usage"] == {
        "input_tokens": 3,
        "output_tokens": 4,
        "reasoning_tokens": 2,
        "total_tokens": 9,
    }
    assert provider.capabilities.protocol == "gemini_generate_content"
    assert provider.capabilities.tool_result_mode == "gemini_parts"
    assert provider.model_spec.to_json_dict()["adapter"] == "tinyagent.gemini_generate_content.v1"


def test_gemini_provider_sends_function_response_history_with_thought_signature() -> None:
    provider = GeminiGenerateContentProvider(
        GeminiGenerateContentConfig(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="test-key",
            model="gemini-test",
        )
    )
    state = _state_stub()
    state.tool_steps.append(
        ToolStep(
            call=ToolCall(
                id="call_gemini",
                name="sample_tool",
                args={"value": "input"},
                metadata={"gemini": {"thoughtSignature": "sig-123"}},
            ),
            result=ToolResult(
                tool_name="sample_tool",
                call_id="call_gemini",
                output="tool output",
                ok=True,
                summary="sample ok",
                data={"output_tokens": 2},
            ),
        )
    )

    payload = provider.build_payload([Message(role="user", content="continue")], [SampleTool()], _request_stub(state))

    assert payload["contents"][-2] == {
        "role": "model",
        "parts": [
            {
                "functionCall": {
                    "id": "call_gemini",
                    "name": "sample_tool",
                    "args": {"value": "input"},
                },
                "thoughtSignature": "sig-123",
            }
        ],
    }
    assert payload["contents"][-1] == {
        "role": "user",
        "parts": [
            {
                "functionResponse": {
                    "id": "call_gemini",
                    "name": "sample_tool",
                    "response": {
                        "ok": True,
                        "output": "tool output",
                        "summary": "sample ok",
                        "data": {"output_tokens": 2},
                    },
                }
            }
        ],
    }


def test_gemini_provider_factory_uses_shared_model_env() -> None:
    provider = provider_for(
        ProviderSpec(kind="gemini", model="gemini-test"),
        "task",
        env={"TINYAGENT_MODEL_API_KEY": "key"},
    )

    assert isinstance(provider, GeminiGenerateContentProvider)
    assert provider.name == "gemini"
    assert provider.model == "gemini-test"
    assert provider.model_spec.protocol == "gemini_generate_content"


def test_gemini_parser_rejects_malformed_function_call() -> None:
    with pytest.raises(ProviderError, match="must be a JSON object"):
        parse_generate_content(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [{"functionCall": {"id": "call_1", "name": "sample_tool", "args": "bad"}}],
                        }
                    }
                ]
            }
        )


def test_kernel_fails_clearly_when_provider_does_not_support_tools(tmp_path) -> None:
    class TextOnlyProvider:
        name = "text-only"
        capabilities = ModelCapabilities(supports_tools=False, protocol="none", tool_result_mode="none")

        def complete(self, messages, tools, request):
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
            protocol="anthropic_messages",
            edit_style="str_replace",
            capabilities=ModelCapabilities(context_window=20_000, max_output_tokens=2_000),
        )

        def __init__(self) -> None:
            self.tools = []

        def complete(self, messages, tools, request):
            del messages, request
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
    assert provider.tools == [
        "read_file",
        "context_search",
        "context_read",
        "search_code",
        "list_skills",
        "load_skill",
        "str_replace_edit",
        "shell",
    ]
    assert state.model_spec["edit_style"] == "str_replace"
    started = next(event for event in state.events if event.type == "run.started")
    assert started.data["provider"] == "anthropic"
    assert started.data["model"] == "claude-test"
    assert started.data["protocol"] == "anthropic_messages"
    assert started.data["capabilities"]["context_window"] == 20_000
    assert started.data["adapter"] == "unknown"
    report_event = next(event for event in state.events if event.type == "context.report.written")
    report = json.loads((state.output_dir / report_event.data["context_report_artifact"]).read_text())
    assert report["budget"] == 18_000
    assert state.context_token_estimate <= 18_000


def test_model_spec_hidden_edit_tool_is_blocked(tmp_path) -> None:
    class ClaudeLikeProvider:
        name = "claude-like"
        model_spec = ModelSpec(provider="anthropic", model="claude-test", protocol="anthropic_messages", edit_style="str_replace")

        def complete(self, messages, tools, request):
            del messages, tools, request
            return ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": "*** Begin Patch\n*** End Patch"}),))

    state = Kernel(
        model=ClaudeLikeProvider(),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=AllowAllPolicy(),
        workspace_mode="current",
        budgets=RunBudgets(max_model_calls=1),
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
        _request_stub(),
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
        provider.stream([Message(role="user", content="use tool")], [SampleTool()], _request_stub()),
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
        _request_stub(),
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

    response = provider.complete([], [], _request_stub())

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
        provider.complete([], [], _request_stub())


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
        provider.complete([], [], _request_stub())


def test_openai_responses_config_reads_environment() -> None:
    config = OpenAIResponsesConfig.from_env(
        {
            "TINYAGENT_MODEL_BASE_URL": "https://models.example.test/v1",
            "TINYAGENT_MODEL_API_KEY": "key",
            "TINYAGENT_MODEL_NAME": "model",
            "TINYAGENT_MODEL_TIMEOUT_SECONDS": "12",
            "TINYAGENT_MODEL_CONTEXT_WINDOW": "64000",
            "TINYAGENT_MODEL_MAX_OUTPUT_TOKENS": "4000",
            "TINYAGENT_MODEL_PARALLEL_TOOL_CALLS": "true",
            "TINYAGENT_MODEL_PROMPT_CACHE_KEY": "thread-123",
            "TINYAGENT_MODEL_REASONING_JSON": '{"effort":"medium"}',
            "TINYAGENT_MODEL_EXTRA_BODY_JSON": '{"temperature":0}',
        }
    )

    assert config.base_url == "https://models.example.test/v1"
    assert config.api_key == "key"
    assert config.model == "model"
    assert config.timeout_seconds == 12
    assert config.context_window == 64_000
    assert config.max_output_tokens == 4_000
    assert config.parallel_tool_calls is True
    assert config.prompt_cache_key == "thread-123"
    assert config.reasoning == {"effort": "medium"}
    assert config.extra_body == {"temperature": 0}


def test_openai_responses_provider_sends_responses_payload_and_parses_tool_calls() -> None:
    provider = RecordingResponsesProvider(
        {
            "id": "resp_123",
            "conversation": {"id": "conv_123"},
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Working."}],
                },
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "sample_tool",
                    "arguments": json.dumps({"value": "done"}),
                },
            ],
        }
    )

    response = provider.complete(
        [
            Message(role="system", content="system instructions"),
            Message(role="user", content="use the sample tool"),
        ],
        [SampleTool()],
        _request_stub(),
    )

    assert provider.payloads == [
        {
            "model": "test-model",
            "instructions": "system instructions",
            "input": [{"role": "user", "content": "use the sample tool"}],
            "store": False,
            "prompt_cache_key": "run_test",
            "max_output_tokens": 8000,
            "tools": [
                {
                    "type": "function",
                    "name": "sample_tool",
                    "description": "Sample tool.",
                    "parameters": SampleTool.schema["parameters"],
                    "strict": False,
                }
            ],
            "parallel_tool_calls": True,
        }
    ]
    assert response.content == "Working."
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls == (ToolCall(id="call_1", name="sample_tool", args={"value": "done"}),)
    assert provider.capabilities.protocol == "openai_responses"
    assert provider.capabilities.tool_result_mode == "responses_items"
    assert provider.model_spec.to_json_dict()["adapter"] == "tinyagent.openai_responses.v1"


def test_openai_responses_provider_sends_cache_key_and_configured_parallel_tool_calls() -> None:
    provider = RecordingResponsesProvider(
        {
            "id": "resp_123",
            "conversation": {"id": "conv_123"},
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "Done."}],
                }
            ],
        },
        config=OpenAIResponsesConfig(
            base_url="https://models.example.test/v1",
            api_key="test-key",
            model="test-model",
            parallel_tool_calls=True,
            prompt_cache_key="thread-abc",
        ),
    )

    response = provider.complete([Message(role="user", content="use the sample tool")], [SampleTool()], _request_stub())

    assert response.content == "Done."
    assert provider.capabilities.supports_parallel_tool_calls is True
    assert provider.capabilities.supports_prompt_cache_key is True
    assert provider.payloads[0]["prompt_cache_key"] == "thread-abc"
    assert provider.payloads[0]["parallel_tool_calls"] is True
    assert response.conversation_state is not None
    assert response.conversation_state.to_json_dict() == {
        "adapter": "tinyagent.openai_responses.v1",
        "conversation_id": "conv_123",
        "mode": "stateless_replay",
        "prompt_cache_key": "thread-abc",
        "provider": "openai-responses",
        "response_id": "resp_123",
    }


def test_openai_responses_provider_sends_native_tool_history_without_duplicate_recent_text() -> None:
    provider = OpenAIResponsesProvider(
        OpenAIResponsesConfig(
            base_url="https://models.example.test/v1",
            api_key="test-key",
            model="test-model",
        )
    )
    state = _state_stub()
    state.tool_steps.append(
        ToolStep(
            call=ToolCall(id="call_read", name="read_file", args={"path": "hello.txt"}),
            result=ToolResult(
                tool_name="read_file",
                call_id="call_read",
                output="hello.txt\n1: hello",
                ok=True,
                summary="Read hello.txt",
                data={
                    "path": "hello.txt",
                    "start_line": 1,
                    "line_count": 1,
                    "total_lines": 1,
                    "complete_file": True,
                    "shown_line_start": 1,
                    "shown_line_end": 1,
                    "output_tokens": 5,
                },
            ),
        )
    )

    payload = provider.build_payload(
        [
            Message(role="system", content="system instructions"),
            Message(role="user", content="task"),
            Message(
                role="user",
                content="Recent tool results:\nSHOULD_NOT_BE_SENT",
                meta={"context_layer": "recent_tool_steps"},
            ),
        ],
        [SampleTool()],
        _request_stub(state),
    )

    assert payload["instructions"] == "system instructions"
    assert {"role": "user", "content": "Recent tool results:\nSHOULD_NOT_BE_SENT"} not in payload["input"]
    assert payload["input"][-2] == {
        "type": "function_call",
        "id": "call_read",
        "call_id": "call_read",
        "name": "read_file",
        "arguments": '{"path": "hello.txt"}',
        "status": "completed",
    }
    assert payload["input"][-1]["type"] == "function_call_output"
    assert payload["input"][-1]["call_id"] == "call_read"
    assert '"complete_file": true' in payload["input"][-1]["output"]
    assert "hello.txt\n1: hello" in payload["input"][-1]["output"]


def test_openai_responses_provider_marks_failed_native_tool_outputs_incomplete() -> None:
    provider = OpenAIResponsesProvider(
        OpenAIResponsesConfig(
            base_url="https://models.example.test/v1",
            api_key="test-key",
            model="test-model",
        )
    )
    state = _state_stub()
    state.tool_steps.append(
        ToolStep(
            call=ToolCall(id="call_shell", name="shell", args={"cmd": "false"}),
            result=ToolResult(
                tool_name="shell",
                call_id="call_shell",
                output="exit 1",
                ok=False,
                summary="command failed",
                failure_kind="command_failed",
            ),
        )
    )

    payload = provider.build_payload([Message(role="user", content="continue")], [SampleTool()], _request_stub(state))

    assert payload["input"][-1]["type"] == "function_call_output"
    assert payload["input"][-1]["status"] == "incomplete"
    assert "Failure kind: command_failed" in payload["input"][-1]["output"]


def test_openai_responses_provider_streams_text_tool_args_and_usage() -> None:
    provider = StreamingResponsesProvider(
        [
            {
                "type": "response.output_text.delta",
                "item_id": "msg_1",
                "delta": "Working ",
            },
            {
                "type": "response.output_item.added",
                "output_index": 1,
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "sample_tool",
                    "arguments": "",
                },
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "output_index": 1,
                "delta": '{"value":',
            },
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "output_index": 1,
                "delta": '"done"}',
            },
            {
                "type": "response.function_call_arguments.done",
                "item_id": "fc_1",
                "output_index": 1,
                "item": {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "sample_tool",
                    "arguments": '{"value":"done"}',
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "status": "completed",
                    "output": [{"type": "function_call"}],
                    "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
                },
            },
        ]
    )

    response = assemble_model_deltas(
        provider.name,
        provider.stream([Message(role="user", content="use tool")], [SampleTool()], _request_stub()),
    )

    assert provider.payloads == [
        {
            "model": "test-model",
            "instructions": "",
            "input": [{"role": "user", "content": "use tool"}],
            "store": False,
            "prompt_cache_key": "run_test",
            "max_output_tokens": 8000,
            "tools": [
                {
                    "type": "function",
                    "name": "sample_tool",
                    "description": "Sample tool.",
                    "parameters": SampleTool.schema["parameters"],
                    "strict": False,
                }
            ],
            "parallel_tool_calls": True,
            "stream": True,
        }
    ]
    assert response.content == "Working "
    assert response.tool_calls == (ToolCall(id="call_1", name="sample_tool", args={"value": "done"}),)
    assert response.finish_reason == "tool_calls"
    assert response.raw["usage"] == {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}


def test_openai_responses_stream_parser_maps_reasoning_summary_delta() -> None:
    deltas = list(
        parse_response_stream_event(
            {
                "type": "response.reasoning_summary_text.delta",
                "item_id": "rs_1",
                "delta": "reasoning",
            }
        )
    )

    assert deltas == [
        ModelDelta(
            kind="reasoning_summary_delta",
            item_id="rs_1",
            delta="reasoning",
            data={"provider_field": "response.reasoning_summary_text.delta"},
        )
    ]


def test_open_responses_provider_sends_partial_stateless_payload() -> None:
    provider = RecordingOpenResponsesProvider(
        {
            "id": "resp_open_123",
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_open",
                    "name": "sample_tool",
                    "arguments": json.dumps({"value": "done"}),
                }
            ],
        }
    )

    response = provider.complete(
        [Message(role="system", content="system instructions"), Message(role="user", content="use the tool")],
        [SampleTool()],
        _request_stub(),
    )

    assert provider.payloads == [
        {
            "model": "test-model",
            "instructions": "system instructions",
            "input": [{"role": "user", "content": "use the tool"}],
            "max_output_tokens": 8000,
            "tools": [
                {
                    "type": "function",
                    "name": "sample_tool",
                    "description": "Sample tool.",
                    "parameters": SampleTool.schema["parameters"],
                    "strict": False,
                }
            ],
            "parallel_tool_calls": True,
        }
    ]
    assert "store" not in provider.payloads[0]
    assert "prompt_cache_key" not in provider.payloads[0]
    assert "reasoning" not in provider.payloads[0]
    assert response.tool_calls == (ToolCall(id="call_open", name="sample_tool", args={"value": "done"}),)
    assert response.conversation_state is not None
    assert response.conversation_state.to_json_dict() == {
        "adapter": "tinyagent.open_responses.v1",
        "mode": "stateless_replay",
        "provider": "open-responses",
        "response_id": "resp_open_123",
    }
    assert provider.capabilities.protocol == "open_responses"
    assert provider.capabilities.tool_result_mode == "responses_items"
    assert provider.capabilities.supports_prompt_cache_key is False
    assert provider.capabilities.supports_stateful_responses is False
    assert provider.capabilities.supports_reasoning is False


def test_open_responses_config_requires_base_url_and_rejects_stateful_fields() -> None:
    with pytest.raises(ProviderError, match="TINYAGENT_MODEL_BASE_URL is required"):
        OpenAIResponsesConfig.open_responses_from_env({"TINYAGENT_MODEL_NAME": "model"})

    with pytest.raises(ProviderError, match="stateless by default"):
        OpenAIResponsesConfig.open_responses_from_env(
            {
                "TINYAGENT_MODEL_BASE_URL": "http://127.0.0.1:11434/v1",
                "TINYAGENT_MODEL_NAME": "model",
                "TINYAGENT_MODEL_EXTRA_BODY_JSON": '{"previous_response_id":"resp_1"}',
            }
        )

    with pytest.raises(ProviderError, match="REASONING_JSON is not supported"):
        OpenAIResponsesConfig.open_responses_from_env(
            {
                "TINYAGENT_MODEL_BASE_URL": "http://127.0.0.1:11434/v1",
                "TINYAGENT_MODEL_NAME": "model",
                "TINYAGENT_MODEL_REASONING_JSON": '{"effort":"low"}',
            }
        )


def test_openai_codex_provider_uses_responses_transport_with_codex_auth() -> None:
    provider = OpenAIResponsesProvider.codex_from_env(
        {
            "TINYAGENT_CODEX_BEARER_TOKEN": "codex-token",
            "TINYAGENT_MODEL_NAME": "gpt-5.5-codex",
        }
    )

    assert provider.name == "openai-codex"
    assert provider.adapter == "tinyagent.openai_codex_responses.v1"
    assert provider.config.base_url == "https://chatgpt.com/backend-api/codex"
    assert provider.config.api_key == "codex-token"
    assert provider.config.send_max_output_tokens is False
    assert provider.model_spec.protocol == "openai_responses"
    assert provider.build_payload([Message(role="user", content="hello")], [], _request_stub()) == {
        "model": "gpt-5.5-codex",
        "instructions": "",
        "input": [{"role": "user", "content": "hello"}],
        "store": False,
        "prompt_cache_key": "run_test",
    }


def test_provider_registry_creates_responses_codex_open_responses_and_gemini_providers() -> None:
    responses = provider_for(
        ProviderSpec(kind="openai-responses", model="gpt-test"),
        "task",
        env={"TINYAGENT_MODEL_API_KEY": "key"},
    )
    codex = provider_for(
        ProviderSpec(kind="openai-codex", model="gpt-codex-test"),
        "task",
        env={"TINYAGENT_CODEX_BEARER_TOKEN": "token"},
    )
    open_responses = provider_for(
        ProviderSpec(kind="open-responses", model="local-responses-test"),
        "task",
        env={"TINYAGENT_MODEL_BASE_URL": "http://127.0.0.1:11434/v1"},
    )
    gemini = provider_for(
        ProviderSpec(kind="gemini", model="gemini-test"),
        "task",
        env={"TINYAGENT_MODEL_API_KEY": "key"},
    )

    assert responses.name == "openai-responses"
    assert codex.name == "openai-codex"
    assert open_responses.name == "open-responses"
    assert open_responses.model_spec.protocol == "open_responses"
    assert gemini.name == "gemini"
    assert gemini.model_spec.protocol == "gemini_generate_content"


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


def _state_stub(run_id: str = "run_test") -> RunState:
    return RunState.create("test", workspace=Workspace(Path(".")), run_id=run_id)


def _request_stub(state: RunState | None = None, run_id: str = "run_test") -> ModelRequestContext:
    return ModelRequestContext.from_run_state(state or _state_stub(run_id))
