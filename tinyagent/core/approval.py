"""Approval resolution and policy decision event recording."""

from __future__ import annotations

from tinyagent.core.contracts import ApprovalHandler
from tinyagent.core.run_control import RunCancelled
from tinyagent.core.state import ApprovalGrant, ApprovalRequest, ApprovalResolution, PolicyDecision, RunState, ToolCall


def record_policy_decision(state: RunState, call: ToolCall, decision: PolicyDecision) -> None:
    approval_id = decision.approval.approval_id if decision.approval else None
    state.emit(
        "policy.evaluated",
        {
            "tool_call_id": call.id,
            "tool": call.name,
            "kind": decision.kind,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "redacted": decision.redacted,
            "approval_id": approval_id,
            "matched_rule": decision.matched_rule,
            "permission": decision.permission,
            "capability": decision.permission,
            "source": "policy",
            "recoverability": "request_approval" if decision.kind == "needs_approval" else "choose_alternative",
        },
    )


def resolve_approval(
    state: RunState,
    decision: PolicyDecision,
    *,
    approval_handler: ApprovalHandler | None,
) -> PolicyDecision:
    approval = decision.approval
    if approval is None:
        return PolicyDecision.deny(decision.reason or "approval request missing")

    grant = state.approval_grants.get(approval.grant_key())
    if grant is not None:
        state.emit(
            "approval.resolved",
            {
                "approval_id": approval.approval_id,
                "decision": "approved",
                "scope": grant.scope,
                "reason": "approval_grant",
            },
            visibility="user",
        )
        return PolicyDecision.allow("approved by run-scoped grant")

    state.pending_approvals[approval.approval_id] = approval
    state.emit("approval.requested", approval.to_json_dict(), visibility="user")

    try:
        if state.approval_mode == "never":
            resolution = ApprovalResolution(
                approval_id=approval.approval_id,
                decision="denied",
                reason="approval_mode_never",
            )
        elif state.approval_mode == "yolo":
            resolution = _yolo_resolution(approval)
        elif approval_handler is not None:
            state.start_step("approval_wait", f"approval-{approval.approval_id}", data={"approval_id": approval.approval_id})
            try:
                resolution = approval_handler.resolve(approval, state)
            except RunCancelled:
                state.finish_step("cancelled", data={"approval_id": approval.approval_id})
                raise
            except Exception as exc:
                resolution = ApprovalResolution(
                    approval_id=approval.approval_id,
                    decision="denied",
                    reason=f"approval handler error: {exc}",
                )
                state.finish_step("failed", data={"approval_id": approval.approval_id, "reason": str(exc)})
            else:
                if resolution.decision == "cancelled":
                    state.finish_step("cancelled", data={"approval_id": approval.approval_id, "decision": resolution.decision})
                else:
                    state.finish_step("completed", data={"approval_id": approval.approval_id, "decision": resolution.decision})
        else:
            resolution = ApprovalResolution(
                approval_id=approval.approval_id,
                decision="denied",
                reason="approval_handler_unavailable",
            )
    finally:
        state.pending_approvals.pop(approval.approval_id, None)

    state.emit("approval.resolved", resolution.to_json_dict(), visibility="user")
    if resolution.decision == "approved":
        if resolution.scope == "run":
            state.approval_grants[approval.grant_key()] = ApprovalGrant(
                approval_id=approval.approval_id,
                grant_key=approval.grant_key(),
                scope="run",
            )
        return PolicyDecision.allow(resolution.reason or "approved")
    return PolicyDecision.deny(
        resolution.reason or f"approval {resolution.decision}",
        matched_rule=decision.matched_rule,
        permission=decision.permission,
    )


def _yolo_resolution(approval: ApprovalRequest) -> ApprovalResolution:
    if approval.action_kind in {"network", "workspace_escape", "shell"}:
        return ApprovalResolution(
            approval_id=approval.approval_id,
            decision="denied",
            reason=f"approval-mode=yolo does not allow {approval.action_kind}",
        )
    return ApprovalResolution(
        approval_id=approval.approval_id,
        decision="approved",
        scope="once",
        reason="approval_mode_yolo_in_workspace",
    )
