import type { Approval } from "../protocol/events";

export function renderApprovalModal(approval: Approval | null): string {
  if (!approval) return "";
  return [
    "APPROVAL REQUIRED",
    `Tool: ${approval.tool_name}`,
    `Risk: ${approval.risk}`,
    approval.command ? `Command: ${approval.command}` : `Args: ${approval.args_preview}`,
    "/approve  /deny",
  ].join("\n");
}
