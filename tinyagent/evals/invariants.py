"""Reusable event invariant checks for run traces."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import PurePosixPath

from tinyagent.core.events import Event

STEP_TERMINALS = {"step.completed", "step.failed", "step.cancelled", "step.timeout", "step.idle_timeout"}
RUN_TERMINALS = {"run.completed", "run.failed", "run.cancelled", "run.timed_out"}
TURN_TERMINALS = {"turn.completed", "turn.failed", "turn.interrupted"}
MODEL_TERMINALS = {"model.call.completed", "model.call.failed", "model.cancelled", "model.timeout", "model.idle_timeout"}
TOOL_TERMINALS = {"tool.execution.completed", "tool.execution.failed", "tool.execution.cancelled"}


def check_event_invariants(events: Sequence[Event]) -> list[str]:
    failures: list[str] = []
    if not events:
        return ["event stream is empty"]

    _check_sequence(events, failures)
    _check_run_order(events, failures)
    _check_turns(events, failures)
    _check_steps(events, failures)
    _check_model_calls(events, failures)
    _check_tool_calls(events, failures)
    _check_workspace_deltas(events, failures)
    _check_workspace_mutations(events, failures)
    _check_approvals(events, failures)
    _check_artifacts(events, failures)
    _check_finalization(events, failures)
    return failures


def _check_sequence(events: Sequence[Event], failures: list[str]) -> None:
    seqs = [event.seq for event in events]
    if seqs != sorted(seqs) or len(seqs) != len(set(seqs)):
        failures.append("event seq must be strictly increasing")
    terminal_runs = [event for event in events if event.type in RUN_TERMINALS]
    if not terminal_runs:
        failures.append("terminal run event is missing")
    if len(terminal_runs) > 1:
        failures.append("terminal run event appears more than once")


def _check_run_order(events: Sequence[Event], failures: list[str]) -> None:
    started = next((event for event in events if event.type == "run.started"), None)
    if started is None:
        failures.append("run.started is missing")
        return
    for event in events:
        if event.type.startswith(("model.", "tool.execution", "policy.")) and event.seq < started.seq:
            failures.append(f"{event.type} appears before run.started")


def _check_turns(events: Sequence[Event], failures: list[str]) -> None:
    active: dict[str, Event] = {}
    for event in events:
        turn_id = str(event.data.get("turn_id") or event.turn_id or "")
        if event.type == "turn.started":
            if not turn_id:
                failures.append("turn.started missing turn_id")
                continue
            if turn_id in active:
                failures.append(f"turn started twice before closure: {turn_id}")
            active[turn_id] = event
        elif event.type in TURN_TERMINALS:
            if not turn_id:
                failures.append(f"{event.type} missing turn_id")
                continue
            if turn_id not in active:
                failures.append(f"turn terminal without start: {turn_id}")
            else:
                active.pop(turn_id)
        elif event.type in RUN_TERMINALS and active:
            failures.append(f"run terminal with open turns: {sorted(active)}")
    if active:
        failures.append(f"open turns after event stream: {sorted(active)}")


def _check_steps(events: Sequence[Event], failures: list[str]) -> None:
    active: dict[str, Event] = {}
    for event in events:
        if event.type == "step.started":
            step_id = str(event.data.get("step_id") or "")
            if not step_id:
                failures.append("step.started missing step_id")
                continue
            if step_id in active:
                failures.append(f"step started twice before closure: {step_id}")
            active[step_id] = event
        elif event.type in STEP_TERMINALS:
            step_id = str(event.data.get("step_id") or "")
            if not step_id:
                failures.append(f"{event.type} missing step_id")
                continue
            if step_id not in active:
                failures.append(f"step terminal without start: {step_id}")
            else:
                active.pop(step_id)
        elif event.type in RUN_TERMINALS and active:
            failures.append(f"run terminal with open steps: {sorted(active)}")
    if active:
        failures.append(f"open steps after event stream: {sorted(active)}")


def _check_model_calls(events: Sequence[Event], failures: list[str]) -> None:
    active: dict[str, Event] = {}
    started_seq: dict[str, int] = {}
    assembly_seq: dict[str, int] = {}
    assembly_counts: dict[str, int] = {}
    terminal_seq: dict[str, int] = {}
    for event in events:
        model_call_id = _string(event.data.get("model_call_id"))
        if event.type == "model.call.started":
            if not model_call_id:
                failures.append("model.call.started missing model_call_id")
                continue
            active[model_call_id] = event
            started_seq[model_call_id] = event.seq
        elif event.type == "model.tool_call.assembly.completed":
            tool_call_id = _string(event.data.get("tool_call_id"))
            tool = _string(event.data.get("tool"))
            if not model_call_id:
                failures.append(f"model tool assembly completed missing model_call_id: {tool_call_id or '(missing tool_call_id)'}")
                continue
            malformed = False
            if not tool_call_id:
                failures.append(f"model tool assembly completed missing tool_call_id: {model_call_id}")
                malformed = True
            if not tool:
                failures.append(f"model tool assembly completed missing tool: {tool_call_id or model_call_id}")
                malformed = True
            if "args" not in event.data:
                failures.append(f"model tool assembly completed missing args: {tool_call_id or model_call_id}")
                malformed = True
            if model_call_id not in started_seq:
                failures.append(f"model tool assembly without model start: {model_call_id}")
            if not malformed:
                assembly_counts[model_call_id] = assembly_counts.get(model_call_id, 0) + 1
            key = _tool_call_key(event)
            assembly_seq.setdefault(key, event.seq)
        elif event.type in MODEL_TERMINALS:
            if not model_call_id:
                failures.append(f"{event.type} missing model_call_id")
                continue
            if model_call_id not in started_seq:
                failures.append(f"model terminal without start: {model_call_id}")
            if event.type == "model.call.completed":
                expected = event.data.get("tool_call_count")
                if isinstance(expected, int):
                    actual = assembly_counts.get(model_call_id, 0)
                    if actual != expected:
                        failures.append(
                            f"model call tool_call_count mismatch: {model_call_id} "
                            f"expected {expected}, saw {actual} completed assembly event(s)"
                        )
            terminal_seq[model_call_id] = event.seq
            active.pop(model_call_id, None)
    for event in events:
        if event.type != "tool.execution.started":
            continue
        key = _tool_call_key(event)
        if key and key in assembly_seq and assembly_seq[key] > event.seq:
            failures.append(f"tool execution started before model assembly completed: {key}")
        model_call_id = _string(event.data.get("model_call_id"))
        if key and model_call_id and terminal_seq.get(model_call_id, event.seq) > event.seq:
            failures.append(f"tool execution started before model call completed: {key}")
    if active:
        failures.append(f"open model calls after event stream: {sorted(active)}")


def _check_tool_calls(events: Sequence[Event], failures: list[str]) -> None:
    active: dict[str, Event] = {}
    assembled_seq: dict[str, int] = {}
    policy_seq: dict[str, int] = {}
    started_seen: set[str] = set()
    terminal_seen: set[str] = set()
    terminal_without_start: dict[str, Event] = {}
    blocked_seen: set[str] = set()
    output_snapshots = {
        _tool_call_key(event): event.seq
        for event in events
        if event.type == "tool.execution.output.snapshot" and _tool_call_key(event)
    }
    for event in events:
        tool_call_id = _string(event.data.get("tool_call_id"))
        if not tool_call_id:
            continue
        if event.type == "model.tool_call.assembly.completed":
            if tool_call_id in assembled_seq:
                failures.append(f"model tool call assembled more than once: {tool_call_id}")
            assembled_seq[tool_call_id] = event.seq
        elif event.type == "policy.evaluated":
            policy_seq[tool_call_id] = event.seq
        elif event.type == "tool.execution.started":
            if tool_call_id not in assembled_seq:
                failures.append(f"tool execution started without model tool assembly: {tool_call_id}")
            if tool_call_id in active:
                failures.append(f"tool execution started twice before closure: {tool_call_id}")
            active[tool_call_id] = event
            started_seen.add(tool_call_id)
            if tool_call_id not in policy_seq or policy_seq[tool_call_id] > event.seq:
                failures.append(f"tool execution started before policy evaluation: {tool_call_id}")
        elif event.type in TOOL_TERMINALS:
            if tool_call_id not in assembled_seq:
                failures.append(f"tool execution terminal without model tool assembly: {tool_call_id}")
            if event.type in {"tool.execution.completed", "tool.execution.failed"} and _tool_event_has_artifact_output(event):
                snapshot_seq = output_snapshots.get(tool_call_id)
                if snapshot_seq is None:
                    failures.append(f"tool execution artifact output without snapshot: {tool_call_id}")
                elif snapshot_seq > event.seq:
                    failures.append(f"tool execution output snapshot after terminal: {tool_call_id}")
            if tool_call_id in terminal_seen:
                failures.append(f"tool execution terminal appears more than once: {tool_call_id}")
            terminal_seen.add(tool_call_id)
            if tool_call_id not in active and tool_call_id not in started_seen:
                terminal_without_start[tool_call_id] = event
            active.pop(tool_call_id, None)
        elif event.type == "tool.execution.blocked":
            if tool_call_id in blocked_seen:
                failures.append(f"tool execution blocked appears more than once: {tool_call_id}")
            blocked_seen.add(tool_call_id)
            if tool_call_id in policy_seq and policy_seq[tool_call_id] > event.seq:
                failures.append(f"tool blocked before policy evaluation: {tool_call_id}")
    if active:
        failures.append(f"open tool executions after event stream: {sorted(active)}")
    for tool_call_id in sorted(assembled_seq):
        if tool_call_id not in terminal_seen:
            failures.append(f"model tool call has no terminal tool result: {tool_call_id}")
    for tool_call_id in sorted(blocked_seen):
        if tool_call_id not in terminal_seen:
            failures.append(f"tool blocked without terminal result: {tool_call_id}")
    for tool_call_id, event in sorted(terminal_without_start.items()):
        if event.data.get("blocked") and tool_call_id not in blocked_seen:
            failures.append(f"tool execution terminal marked blocked without blocked event: {tool_call_id}")
        elif tool_call_id not in blocked_seen:
            failures.append(f"tool execution terminal without start: {tool_call_id}")


def _check_workspace_deltas(events: Sequence[Event], failures: list[str]) -> None:
    active: dict[str, Event] = {}
    completed: set[str] = set()
    for event in events:
        tool_call_id = _string(event.data.get("tool_call_id"))
        if event.type == "workspace.delta.started":
            if not tool_call_id:
                failures.append("workspace.delta.started missing tool_call_id")
                continue
            if tool_call_id in active:
                failures.append(f"workspace delta started twice before completion: {tool_call_id}")
            active[tool_call_id] = event
        elif event.type == "workspace.delta.completed":
            if not tool_call_id:
                failures.append("workspace.delta.completed missing tool_call_id")
                continue
            if tool_call_id in completed:
                failures.append(f"workspace delta completed more than once: {tool_call_id}")
            completed.add(tool_call_id)
            if tool_call_id not in active:
                failures.append(f"workspace delta completed without start: {tool_call_id}")
            else:
                active.pop(tool_call_id)
    if active:
        failures.append(f"open workspace deltas after event stream: {sorted(active)}")


def _check_workspace_mutations(events: Sequence[Event], failures: list[str]) -> None:
    planned: set[str] = set()
    active: dict[str, Event] = {}
    completed: set[str] = set()
    for event in events:
        tool_call_id = _string(event.data.get("tool_call_id"))
        if event.type == "workspace.mutation.planned":
            if not tool_call_id:
                failures.append("workspace.mutation.planned missing tool_call_id")
                continue
            if tool_call_id in planned:
                failures.append(f"workspace mutation planned more than once: {tool_call_id}")
            planned.add(tool_call_id)
        elif event.type == "workspace.mutation.started":
            if not tool_call_id:
                failures.append("workspace.mutation.started missing tool_call_id")
                continue
            if tool_call_id not in planned:
                failures.append(f"workspace mutation started without plan: {tool_call_id}")
            if tool_call_id in active:
                failures.append(f"workspace mutation started twice before completion: {tool_call_id}")
            active[tool_call_id] = event
        elif event.type == "workspace.mutation.completed":
            if not tool_call_id:
                failures.append("workspace.mutation.completed missing tool_call_id")
                continue
            if tool_call_id in completed:
                failures.append(f"workspace mutation completed more than once: {tool_call_id}")
            completed.add(tool_call_id)
            if tool_call_id not in active:
                failures.append(f"workspace mutation completed without start: {tool_call_id}")
            else:
                active.pop(tool_call_id)
    if active:
        failures.append(f"open workspace mutations after event stream: {sorted(active)}")


def _check_approvals(events: Sequence[Event], failures: list[str]) -> None:
    pending: dict[str, Event] = {}
    run_grant_seen = False
    for event in events:
        approval_id = _string(event.data.get("approval_id"))
        if event.type == "approval.requested":
            if not approval_id:
                failures.append("approval.requested missing approval_id")
                continue
            if approval_id in pending:
                failures.append(f"approval requested twice before resolution: {approval_id}")
            pending[approval_id] = event
        elif event.type == "approval.resolved":
            if not approval_id:
                failures.append("approval.resolved missing approval_id")
                continue
            if event.data.get("reason") == "approval_grant":
                if not run_grant_seen:
                    failures.append(f"approval grant reused before run-scoped approval: {approval_id}")
                continue
            if approval_id not in pending:
                failures.append(f"approval resolved without request: {approval_id}")
            else:
                pending.pop(approval_id)
            if event.data.get("decision") == "approved" and event.data.get("scope") == "run":
                run_grant_seen = True
    if pending:
        failures.append(f"unresolved approvals after event stream: {sorted(pending)}")


def _check_artifacts(events: Sequence[Event], failures: list[str]) -> None:
    for event in events:
        for path in _artifact_paths(event):
            if _path_escapes(path):
                failures.append(f"artifact path escapes run output: {path}")


def _check_finalization(events: Sequence[Event], failures: list[str]) -> None:
    started = [event for event in events if event.type == "artifact.finalization.started"]
    completed = [event for event in events if event.type in {"artifact.finalization.completed", "artifact.finalization.failed"}]
    terminal_run = next((event for event in events if event.type in RUN_TERMINALS), None)
    if terminal_run is not None and not started:
        failures.append("artifact finalization is missing")
    if started and not completed:
        failures.append("artifact finalization started without terminal event")
    if completed and not started:
        failures.append("artifact finalization terminal without start")
    if terminal_run is not None and started and completed and not (started[-1].seq < completed[-1].seq < terminal_run.seq):
        failures.append("artifact finalization must complete before terminal run event")


def _artifact_paths(event: Event) -> list[str]:
    paths: list[str] = []
    for key in _ARTIFACT_PATH_KEYS:
        value = event.data.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    if event.type in _ARTIFACT_PATH_EVENTS:
        value = event.data.get("path")
        if isinstance(value, str) and value:
            paths.append(value)
    paths.extend(_nested_artifact_paths(event.data))
    for ref in event.artifact_refs:
        if ref:
            paths.append(ref)
    return paths


_ARTIFACT_PATH_EVENTS = frozenset({"artifact.created", "artifact.materialized"})

_ARTIFACT_PATH_KEYS = frozenset(
    {
        "artifact_path",
        "captured_output_artifact",
        "checkpoint_artifact",
        "context_artifact",
        "context_report_artifact",
        "diff_artifact",
        "final_diff_path",
        "final_output_path",
        "http_request_artifact",
        "logical_request_artifact",
        "output_artifact",
        "output_path",
        "request_artifact",
        "response_artifact",
        "summary_artifact",
    }
)


def _nested_artifact_paths(value: object) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _ARTIFACT_PATH_KEYS and isinstance(item, str) and item:
                paths.append(item)
            elif isinstance(item, dict):
                paths.extend(_nested_artifact_paths(item))
            elif isinstance(item, list | tuple):
                for entry in item:
                    paths.extend(_nested_artifact_paths(entry))
    return paths


def _path_escapes(path: str) -> bool:
    if path.startswith("/"):
        return True
    pure = PurePosixPath(path)
    return any(part == ".." for part in pure.parts)


def _tool_call_key(event: Event) -> str:
    return _string(event.data.get("tool_call_id")) or ""


def _tool_event_has_artifact_output(event: Event) -> bool:
    if _string(event.data.get("artifact_path")):
        return True
    data = event.data.get("data")
    return isinstance(data, dict) and any(
        _string(data.get(key)) for key in ("output_artifact", "context_artifact")
    )


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""
