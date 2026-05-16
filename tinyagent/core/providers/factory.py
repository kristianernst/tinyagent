"""Shared model provider construction."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from tinyagent.core.contracts import ModelProvider
from tinyagent.core.models import FakeModelProvider, ProviderError
from tinyagent.core.providers.anthropic import AnthropicMessagesProvider
from tinyagent.core.providers.gemini import GeminiGenerateContentProvider
from tinyagent.core.providers.openai_compat import OpenAICompatibleProvider
from tinyagent.core.providers.openai_responses import OpenAIResponsesProvider
from tinyagent.core.state import ModelResponse, ToolCall


@dataclass(frozen=True)
class ProviderSpec:
    kind: str
    model: str | None = None
    reasoning: dict[str, Any] | None = None


class ProviderFactory(Protocol):
    kind: str

    def create(self, spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider: ...


class ProviderRegistry:
    def __init__(self, factories: Mapping[str, ProviderFactory] | None = None) -> None:
        self._factories = dict(factories or {})

    def register(self, factory: ProviderFactory) -> None:
        if not factory.kind:
            raise ValueError("provider factory kind is required")
        self._factories[factory.kind] = factory

    def create(self, spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
        factory = self._factories.get(spec.kind)
        if factory is None:
            raise ProviderError(f"Unknown provider: {spec.kind}")
        return factory.create(spec, task, env)

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._factories))


def provider_for(spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
    return DEFAULT_PROVIDER_REGISTRY.create(spec, task, env)


def register_provider_factory(factory: ProviderFactory) -> None:
    DEFAULT_PROVIDER_REGISTRY.register(factory)


class FakeProviderFactory:
    kind = "fake"

    def create(self, spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
        del env
        return FakeModelProvider(_fake_responses(task), model=spec.model or "fake")


class OpenAICompatibleProviderFactory:
    kind = "openai-compatible"

    def create(self, spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
        del task
        values = dict(os.environ if env is None else env)
        if spec.model:
            values["TINYAGENT_MODEL_NAME"] = spec.model
        if spec.reasoning is not None:
            values["TINYAGENT_MODEL_REASONING_JSON"] = json.dumps(spec.reasoning, sort_keys=True)
        return OpenAICompatibleProvider.from_env(values)


class OpenAIResponsesProviderFactory:
    kind = "openai-responses"

    def create(self, spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
        del task
        values = dict(os.environ if env is None else env)
        if spec.model:
            values["TINYAGENT_MODEL_NAME"] = spec.model
        if spec.reasoning is not None:
            values["TINYAGENT_MODEL_REASONING_JSON"] = json.dumps(spec.reasoning, sort_keys=True)
        return OpenAIResponsesProvider.from_env(values)


class OpenAICodexProviderFactory:
    kind = "openai-codex"

    def create(self, spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
        del task
        values = dict(os.environ if env is None else env)
        if spec.model:
            values["TINYAGENT_MODEL_NAME"] = spec.model
        if spec.reasoning is not None:
            values["TINYAGENT_MODEL_REASONING_JSON"] = json.dumps(spec.reasoning, sort_keys=True)
        return OpenAIResponsesProvider.codex_from_env(values)


class OpenResponsesProviderFactory:
    kind = "open-responses"

    def create(self, spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
        del task
        values = dict(os.environ if env is None else env)
        if spec.model:
            values["TINYAGENT_MODEL_NAME"] = spec.model
        if spec.reasoning is not None:
            values["TINYAGENT_MODEL_REASONING_JSON"] = json.dumps(spec.reasoning, sort_keys=True)
        return OpenAIResponsesProvider.open_responses_from_env(values)


class AnthropicProviderFactory:
    kind = "anthropic"

    def create(self, spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
        del task
        values = dict(os.environ if env is None else env)
        if spec.model:
            values["TINYAGENT_MODEL_NAME"] = spec.model
        return AnthropicMessagesProvider.from_env(values)


class GeminiProviderFactory:
    kind = "gemini"

    def create(self, spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
        del task
        values = dict(os.environ if env is None else env)
        if spec.model:
            values["TINYAGENT_MODEL_NAME"] = spec.model
        return GeminiGenerateContentProvider.from_env(values)


DEFAULT_PROVIDER_REGISTRY = ProviderRegistry()
DEFAULT_PROVIDER_REGISTRY.register(AnthropicProviderFactory())
DEFAULT_PROVIDER_REGISTRY.register(FakeProviderFactory())
DEFAULT_PROVIDER_REGISTRY.register(GeminiProviderFactory())
DEFAULT_PROVIDER_REGISTRY.register(OpenAICompatibleProviderFactory())
DEFAULT_PROVIDER_REGISTRY.register(OpenAIResponsesProviderFactory())
DEFAULT_PROVIDER_REGISTRY.register(OpenAICodexProviderFactory())
DEFAULT_PROVIDER_REGISTRY.register(OpenResponsesProviderFactory())


def _fake_responses(task: str) -> list[ModelResponse]:
    if "sleep" in task:
        return [
            ModelResponse(tool_calls=(ToolCall(id="call_sleep", name="shell", args={"cmd": "python -c 'import time; time.sleep(20)'"}),)),
            ModelResponse(content="sleep done", finish_reason="stop"),
        ]
    if "approval" in task:
        return [
            ModelResponse(tool_calls=(ToolCall(id="call_approval", name="shell", args={"cmd": "printf approved > ../approved.txt"}),)),
            ModelResponse(content="approval done", finish_reason="stop"),
        ]
    if "status says done" in task and "notes.txt" in task:
        patch = "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: notes.txt",
                "@@",
                "-status: todo",
                "+status: done",
                "*** End Patch",
            ]
        )
        return [
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "sed -n '1,120p' notes.txt"}),)),
            ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff -- notes.txt"}),)),
            ModelResponse(
                content=(
                    "Fake run updated notes.txt and inspected the diff. "
                    "Verification not run; this fixture has only a harness validation script."
                ),
                finish_reason="stop",
            ),
        ]
    if "Fix the bug in calc.py" in task:
        patch = "\n".join(
            [
                "*** Begin Patch",
                "*** Update File: calc.py",
                "@@",
                "-    return a - b",
                "+    return a + b",
                "*** End Patch",
            ]
        )
        return [
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "sed -n '1,120p' calc.py"}),)),
            ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "pytest"}),)),
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "git diff -- calc.py"}),)),
            ModelResponse(content="Fake run fixed calc.py, ran pytest, and inspected the diff.", finish_reason="stop"),
        ]
    path = _first_mentioned_file(task)
    if path is not None:
        return [
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": f"sed -n '1,120p' {path}"}),)),
            ModelResponse(content=f"Fake run finished after reading {path}.", finish_reason="stop"),
        ]
    return [ModelResponse(content=f"Fake run finished: {task}", finish_reason="stop")]


def _first_mentioned_file(task: str) -> str | None:
    match = re.search(r"(?P<path>[\w./-]+\.[A-Za-z0-9_+-]+)", task)
    return match.group("path") if match else None
