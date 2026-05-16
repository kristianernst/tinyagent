"""Small model provider helpers."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal

from tinyagent.core.contracts import Tool
from tinyagent.core.model_stream import ModelDelta, model_response_to_deltas
from tinyagent.core.state import Message, ModelRequestContext, ModelResponse


class ProviderError(RuntimeError):
    """Raised when a model provider cannot produce a response."""


ModelProtocol = Literal[
    "openai_chat_completions",
    "openai_responses",
    "open_responses",
    "anthropic_messages",
    "gemini_generate_content",
    "none",
]
ToolResultMode = Literal["chat_tool_messages", "responses_items", "anthropic_blocks", "gemini_parts", "none"]


@dataclass(frozen=True)
class ModelCapabilities:
    context_window: int = 128_000
    max_output_tokens: int = 8_000
    supports_tools: bool = True
    supports_parallel_tool_calls: bool = False
    supports_streaming: bool = True
    supports_reasoning: bool = False
    supports_images: bool = False
    supports_prompt_cache_key: bool = False
    supports_stateful_responses: bool = False
    supports_conversation_resource: bool = False
    supports_reasoning_replay: bool = False
    protocol: ModelProtocol = "openai_chat_completions"
    tool_result_mode: ToolResultMode = "chat_tool_messages"

    @property
    def input_budget_tokens(self) -> int:
        return max(1, self.context_window - self.max_output_tokens)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_tools": self.supports_tools,
            "supports_parallel_tool_calls": self.supports_parallel_tool_calls,
            "supports_streaming": self.supports_streaming,
            "supports_reasoning": self.supports_reasoning,
            "supports_images": self.supports_images,
            "supports_prompt_cache_key": self.supports_prompt_cache_key,
            "supports_stateful_responses": self.supports_stateful_responses,
            "supports_conversation_resource": self.supports_conversation_resource,
            "supports_reasoning_replay": self.supports_reasoning_replay,
            "protocol": self.protocol,
            "tool_result_mode": self.tool_result_mode,
        }


DEFAULT_MODEL_CAPABILITIES = ModelCapabilities()


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    protocol: ModelProtocol = "openai_chat_completions"
    adapter: str = "unknown"
    edit_style: Literal["apply_patch", "str_replace", "whole_file"] = "apply_patch"
    prompt_variant: str = "default"
    tokenizer: str = "heuristic"
    capabilities: ModelCapabilities = field(default_factory=lambda: DEFAULT_MODEL_CAPABILITIES)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "protocol": self.protocol,
            "adapter": self.adapter,
            "edit_style": self.edit_style,
            "prompt_variant": self.prompt_variant,
            "tokenizer": self.tokenizer,
            "capabilities": self.capabilities.to_json_dict(),
        }


def model_capabilities(model: object) -> ModelCapabilities:
    spec = getattr(model, "model_spec", None)
    if isinstance(spec, ModelSpec):
        return spec.capabilities
    capabilities = getattr(model, "capabilities", None)
    return capabilities if isinstance(capabilities, ModelCapabilities) else DEFAULT_MODEL_CAPABILITIES


def model_spec(model: object) -> ModelSpec:
    spec = getattr(model, "model_spec", None)
    if isinstance(spec, ModelSpec):
        return spec
    capabilities = model_capabilities(model)
    provider = str(getattr(model, "name", model.__class__.__name__))
    model_name = str(getattr(model, "model", provider))
    adapter = str(getattr(model, "adapter", "unknown"))
    return ModelSpec(provider=provider, model=model_name, protocol=capabilities.protocol, adapter=adapter, capabilities=capabilities)


class FakeModelProvider:
    """Deterministic provider for tests and offline harness runs."""

    name = "fake"
    adapter = "tinyagent.fake.v1"
    capabilities = ModelCapabilities()

    def __init__(self, responses: Sequence[ModelResponse], *, model: str = "fake") -> None:
        self.responses = list(responses)
        self.calls = 0
        self.model = model

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> ModelResponse:
        del messages, tools, request
        self.calls += 1
        if not self.responses:
            raise ProviderError("FakeModelProvider has no response left.")
        return self.responses.pop(0)

    def stream(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> Iterator[ModelDelta]:
        response = self.complete(messages, tools, request)
        yield from model_response_to_deltas(response)
