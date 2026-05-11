"""Offline TinyAgent researcher-reviewer flow.

Run with:
    uv run python examples/research_review_flow.py
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
from tinyagent.core.sdk import Agent, RunResult
from tinyagent.core.state import ModelResponse, ToolCall
from tinyagent.core.tools import default_tools


def prepare_workspace(workspace: Path) -> None:
    docs = workspace / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "product_notes.md").write_text(
        """# Product Notes

TinyAgent should demonstrate small, inspectable coding-agent loops.
The best demo should be offline, deterministic, and easy to review from events.
""",
        encoding="utf-8",
    )
    (docs / "safety_notes.md").write_text(
        """# Safety Notes

The demo should make policy decisions visible.
Unknown shell commands should pass through approval instead of silent execution.
""",
        encoding="utf-8",
    )


def researcher_provider() -> FakeModelProvider:
    patch = """*** Begin Patch
*** Add File: brief.md
+# Agentic Flow Brief
+
+Recommendation: showcase a deterministic coding-agent loop.
+
+Why it works:
+- It uses real TinyAgent tools and events.
+- It is offline and reviewable.
+- It exposes approval for verification commands.
+
+Open risk: keep the example small enough that runtime boundaries stay obvious.
*** End Patch
"""
    return FakeModelProvider(
        [
            ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "docs/product_notes.md"}),)),
            ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "docs/safety_notes.md"}),)),
            ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
            ModelResponse(content="Wrote brief.md with the recommended example and one open risk.", finish_reason="stop"),
        ],
        model="fake-researcher",
    )


def reviewer_provider() -> FakeModelProvider:
    patch = """*** Begin Patch
*** Add File: review.md
+# Review Gate
+
+Decision: accept.
+
+Reason: the brief prioritizes a real coding-agent loop, explicit approval, and reviewable evidence.
+
+Required follow-up: keep optional multi-agent examples as orchestration over runs, not as a graph framework in core.
*** End Patch
"""
    return FakeModelProvider(
        [
            ModelResponse(tool_calls=(ToolCall(name="read_file", args={"path": "brief.md"}),)),
            ModelResponse(tool_calls=(ToolCall(name="apply_patch", args={"patch": patch}),)),
            ModelResponse(content="Accepted the brief and recorded the follow-up boundary in review.md.", finish_reason="stop"),
        ],
        model="fake-reviewer",
    )


async def run_agent(workspace: Path, provider: FakeModelProvider, task: str, run_id: str) -> RunResult:
    agent = Agent(
        workspace=workspace,
        provider=provider,
        profile=TinyPiProfile(),
        tools=default_tools(),
        policy=default_policy(),
    )
    return await agent.run_once(task, run_id=run_id)


async def run_flow(workspace: Path) -> tuple[int, str]:
    prepare_workspace(workspace)
    researcher = await run_agent(
        workspace,
        researcher_provider(),
        "Read the source notes and write a short agentic-flow brief.",
        "example_researcher",
    )
    reviewer = await run_agent(
        workspace,
        reviewer_provider(),
        "Review brief.md, accept or reject it, and write review.md.",
        "example_reviewer",
    )

    brief = (workspace / "brief.md").read_text(encoding="utf-8")
    review = (workspace / "review.md").read_text(encoding="utf-8")
    researcher_counts = Counter(event.type for event in researcher.events)
    reviewer_counts = Counter(event.type for event in reviewer.events)
    passed = (
        researcher.status == "completed"
        and reviewer.status == "completed"
        and "Recommendation: showcase a deterministic coding-agent loop." in brief
        and "Decision: accept." in review
        and "graph framework in core" in review
    )

    lines = [
        "research_review_flow",
        f"workspace: {workspace}",
        f"researcher_status: {researcher.status}",
        f"reviewer_status: {reviewer.status}",
        f"brief: {workspace / 'brief.md'}",
        f"review: {workspace / 'review.md'}",
        f"researcher_tool_calls: {researcher_counts['model.tool_call.assembly.completed']}",
        f"reviewer_tool_calls: {reviewer_counts['model.tool_call.assembly.completed']}",
        f"researcher_final: {researcher.final_output}",
        f"reviewer_final: {reviewer.final_output}",
    ]
    return (0 if passed else 1), "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=None, help="Workspace to create or overwrite for the demo.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = args.workspace or Path(tempfile.mkdtemp(prefix="tinyagent-research-review-"))
    code, output = asyncio.run(run_flow(workspace.resolve()))
    print(output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
