"""Small model provider helpers."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from agentd.contracts import Tool
from agentd.model_stream import ModelDelta, model_response_to_deltas
from agentd.state import Message, ModelResponse, RunState


class ProviderError(RuntimeError):
    """Raised when a model provider cannot produce a response."""


class FakeModelProvider:
    """Deterministic provider for tests and offline harness runs."""

    name = "fake"

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
