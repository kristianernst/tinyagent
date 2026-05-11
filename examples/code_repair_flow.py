"""Offline TinyAgent coding-agent repair flow.

Run with:
    uv run python examples/code_repair_flow.py
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import default_policy
from tinyagent.core.profiles import TinyPiProfile
from tinyagent.core.sdk import Agent
from tinyagent.core.state import ApprovalRequest, ApprovalResolution, ModelResponse, ToolCall
from tinyagent.core.tools import default_tools


class TestApprovalHandler:
    """Approves only the deterministic verification command used by this demo."""

    def __init__(self) -> None:
        self.approved_commands: list[str] = []
        self.denied_commands: list[str] = []

    def resolve(self, request: ApprovalRequest, _state) -> ApprovalResolution:
        command = request.command or request.args_preview
        if request.tool_name == "shell" and "python -m pytest" in command:
            self.approved_commands.append(command)
            return ApprovalResolution(request.approval_id, "approved", scope="once", reason="example_approved_tests")
        self.denied_commands.append(command)
        return ApprovalResolution(request.approval_id, "denied", reason="example_only_approves_tests")


def build_provider() -> FakeModelProvider:
    patch = """*** Begin Patch
*** Update File: calc.py
@@
 def add(a: int, b: int) -> int:
-    return a - b
+    return a + b
*** End Patch
"""
    return FakeModelProvider(
        [
            ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "calc.py"}),)),
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "python -m pytest -q", "timeout_seconds": 20}),)),
            ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
            ModelResponse(tool_calls=(ToolCall(name="shell", args={"cmd": "python -m pytest -q", "timeout_seconds": 20}),)),
            ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "calc.py"}),)),
            ModelResponse(content="Fixed calc.add and verified it with `python -m pytest -q`.", finish_reason="stop"),
        ],
        model="fake-code-repair",
    )


def prepare_workspace(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "calc.py").write_text(
        """def add(a: int, b: int) -> int:
    return a - b
""",
        encoding="utf-8",
    )
    (workspace / "test_calc.py").write_text(
        """from calc import add


def test_adds_two_numbers() -> None:
    assert add(2, 3) == 5
""",
        encoding="utf-8",
    )


async def run_flow(workspace: Path) -> tuple[int, str]:
    prepare_workspace(workspace)
    approvals = TestApprovalHandler()
    agent = Agent(
        workspace=workspace,
        provider=build_provider(),
        profile=TinyPiProfile(),
        tools=default_tools(),
        policy=default_policy(),
        approval_mode="on-request",
        approval_handler=approvals,
    )
    result = await agent.run_once(
        "Fix calc.add, prove the fix with tests, and report the evidence.",
        run_id="example_code_repair",
    )
    event_counts = Counter(event.type for event in result.events)
    fixed_source = (workspace / "calc.py").read_text(encoding="utf-8")
    passed = result.status == "completed" and "return a + b" in fixed_source and len(approvals.approved_commands) == 2

    lines = [
        "code_repair_flow",
        f"workspace: {workspace}",
        f"status: {result.status}",
        f"output_dir: {result.output_dir}",
        f"approved_commands: {approvals.approved_commands}",
        f"final: {result.final_output}",
        f"tool_calls: {event_counts['model.tool_call.assembly.completed']}",
        f"approvals: {event_counts['approval.requested']} requested, {event_counts['approval.resolved']} resolved",
        f"patches: {event_counts['patch.applied']}",
        f"commands: {event_counts['command.completed']} completed, {event_counts['command.failed']} failed",
    ]
    return (0 if passed else 1), "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None, help="Workspace to create or overwrite for the demo.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace or Path(tempfile.mkdtemp(prefix="tinyagent-code-repair-"))
    code, output = asyncio.run(run_flow(workspace.resolve()))
    print(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
