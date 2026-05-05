"""Shared model provider construction."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from agentd.contracts import ModelProvider
from agentd.models import FakeModelProvider, ProviderError
from agentd.providers.openai_compat import OpenAICompatibleProvider
from agentd.state import ModelResponse, ToolCall

ProviderKind = Literal["fake", "openai-compatible"]


@dataclass(frozen=True)
class ProviderSpec:
    kind: ProviderKind
    model: str | None = None
    reasoning: dict[str, Any] | None = None


def provider_for(spec: ProviderSpec, task: str, env: Mapping[str, str] | None = None) -> ModelProvider:
    if spec.kind == "fake":
        return FakeModelProvider(_fake_responses(task), model=spec.model or "fake")
    if spec.kind == "openai-compatible":
        values = dict(os.environ if env is None else env)
        if spec.model:
            values["TINYAGENT_MODEL_NAME"] = spec.model
        if spec.reasoning is not None:
            values["TINYAGENT_MODEL_REASONING_JSON"] = json.dumps(spec.reasoning, sort_keys=True)
        return OpenAICompatibleProvider.from_env(values)
    raise ProviderError(f"Unknown provider: {spec.kind}")


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
