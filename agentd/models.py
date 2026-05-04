"""Small model provider helpers."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal

from agentd.contracts import Tool
from agentd.model_stream import ModelDelta, model_response_to_deltas
from agentd.state import Message, ModelResponse, RunState


class ProviderError(RuntimeError):
    """Raised when a model provider cannot produce a response."""


@dataclass(frozen=True)
class ModelCapabilities:
    context_window: int = 128_000
    max_output_tokens: int = 8_000
    supports_tools: bool = True
    supports_parallel_tools: bool = False
    supports_reasoning: bool = False
    supports_images: bool = False
    supports_prompt_cache: bool = False
    tool_protocol: Literal["chat_completions", "responses", "none"] = "chat_completions"

    @property
    def input_budget_tokens(self) -> int:
        return max(1, self.context_window - self.max_output_tokens)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_tools": self.supports_tools,
            "supports_parallel_tools": self.supports_parallel_tools,
            "supports_reasoning": self.supports_reasoning,
            "supports_images": self.supports_images,
            "supports_prompt_cache": self.supports_prompt_cache,
            "tool_protocol": self.tool_protocol,
        }


DEFAULT_MODEL_CAPABILITIES = ModelCapabilities()


def model_capabilities(model: object) -> ModelCapabilities:
    capabilities = getattr(model, "capabilities", None)
    return capabilities if isinstance(capabilities, ModelCapabilities) else DEFAULT_MODEL_CAPABILITIES


class FakeModelProvider:
    """Deterministic provider for tests and offline harness runs."""

    name = "fake"
    capabilities = ModelCapabilities()

    def __init__(self, responses: Sequence[ModelResponse]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> ModelResponse:
        del messages, tools, state
        self.calls += 1
        if not self.responses:
            raise ProviderError("FakeModelProvider has no response left.")
        return self.responses.pop(0)

    def stream(self, messages: Sequence[Message], tools: Sequence[Tool], state: RunState) -> Iterator[ModelDelta]:
        response = self.complete(messages, tools, state)
        yield from model_response_to_deltas(response)
