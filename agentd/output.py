"""Run output writing for tinyagent."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from agentd.state import RunState


def write_run_outputs(state: RunState) -> None:
    state.output_dir.mkdir(parents=True, exist_ok=True)

    (state.output_dir / "events.jsonl").write_text(
        "".join(json.dumps(event.to_json_dict(), sort_keys=True) + "\n" for event in state.events),
    )
    (state.output_dir / "summary.md").write_text(_summary_text(state))
    (state.output_dir / "metrics.json").write_text(json.dumps(_metrics(state), indent=2, sort_keys=True) + "\n")
    (state.output_dir / "final.diff").write_text(state.final_diff)


def _summary_text(state: RunState) -> str:
    if state.failed:
        return f"# Run failed\n\n{state.failure_reason or 'Unknown failure'}\n"
    return f"# Run finished\n\n{state.summary or 'No summary produced.'}\n"


def _metrics(state: RunState) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "status": "failed" if state.failed else "finished",
        "failure_reason": state.failure_reason,
        "task": state.task,
        "workspace_root": str(state.workspace.root),
        "output_dir": str(state.output_dir),
        "turn_count": state.turn_count,
        "tool_call_count": state.tool_call_count,
        "duration_seconds": state.elapsed_seconds(),
        "budgets": asdict(state.budgets),
        "final_diff_available": bool(state.final_diff),
    }
