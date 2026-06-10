from __future__ import annotations

from collections.abc import Sequence

import pytest

from tinyagent.core.contracts import Tool
from tinyagent.core.kernel import Kernel
from tinyagent.core.profiles import ApexCoderProfile, TinyPiProfile
from tinyagent.core.state import Message, ModelRequestContext, ModelResponse, PolicyDecision, RunState, ToolCall
from tinyagent.core.tools import ApplyPatchTool


class _AllowAllPolicy:
    def evaluate(self, call: ToolCall, state: RunState) -> PolicyDecision:
        return PolicyDecision.allow("allowed")


class _OneShotModel:
    name = "static-model"

    def complete(self, messages: Sequence[Message], tools: Sequence[Tool], request: ModelRequestContext) -> ModelResponse:
        del messages, tools, request
        return ModelResponse(content="done", finish_reason="stop")


def test_tiny_coder_loads_packaged_system_prompt() -> None:
    profile = ApexCoderProfile()
    assert profile.system_prompt_source.startswith("file:")
    assert profile.system_prompt_source.endswith("tiny-coder/system.md")
    prompt = profile.system_prompt()
    assert len(prompt) > 1_500, "default profile fell back to the builtin stub prompt"


def test_tiny_coder_prompt_matches_current_tool_surface() -> None:
    prompt = ApexCoderProfile().system_prompt()
    for tool_name in ("shell", "read_file", "search_code", "apply_patch", "str_replace_edit", "context_search", "load_skill"):
        assert f"`{tool_name}`" in prompt, f"prompt no longer documents {tool_name}"
    for stale_name in ("search_repo", "list_files"):
        assert stale_name not in prompt, f"prompt references retired tool {stale_name}"


def test_explicit_missing_system_prompt_path_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="System prompt file not found"):
        ApexCoderProfile(system_prompt_path=tmp_path / "missing.md")


def test_tiny_pi_reports_builtin_prompt_source() -> None:
    assert TinyPiProfile().system_prompt_source == "builtin:tiny-pi"


def test_run_started_records_system_prompt_source(tmp_path) -> None:
    kernel = Kernel(model=_OneShotModel(), profile=ApexCoderProfile(), tools=[], policy=_AllowAllPolicy())
    state = kernel.run("answer directly", workspace=tmp_path)
    started = next(event for event in state.events if event.type == "run.started")
    assert started.data["system_prompt_source"].startswith("file:")
    assert started.data["system_prompt_source"].endswith("tiny-coder/system.md")


def test_apply_patch_schema_documents_patch_format() -> None:
    description = ApplyPatchTool.schema["description"]
    assert "*** Begin Patch" in description
    assert "*** Update File:" in description
    assert "*** Add File:" in description
    assert "*** Delete File:" in description
