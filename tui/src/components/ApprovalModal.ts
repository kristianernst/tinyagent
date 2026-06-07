import type { Approval } from "../protocol/events";

export function renderApprovalModal(approval: Approval | null): string {
  if (!approval) return "";
  const commandLabel = approval.command ? "command" : "args";
  const command = approval.command || approval.args_preview;
  const cwd = stringField(approval, "cwd");
  const turnId = stringField(approval, "turn_id");
  const requestedBy = turnId ? `requested by: agent · ${turnId}` : "requested by: agent";
  return [
    `⦗ approve ⦘ ${approval.tool_name}`,
    line(commandLabel, command),
    cwd ? line("in", cwd) : "",
    `  ${requestedBy}`,
    `  risk: ${approval.risk} · review first`,
    "",
    "  ⌜y⌟ allow once         ⌜a⌟ allow for session",
    "  ⌜n⌟ deny               ⌜e⌟ edit command",
    "  esc dismisses",
  ]
    .filter(Boolean)
    .join("\n");
}

function line(label: string, value: string): string {
  return `  ${label.padEnd(12)}${value}`;
}

function stringField(value: object, key: string): string {
  const field = (value as Record<string, unknown>)[key];
  return typeof field === "string" ? field.trim() : "";
}
