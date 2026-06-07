import type { ToolCallView } from "../state/reducer";
import { toolDisplayName } from "../ui/toolLabels";

export function renderToolTimeline(tools: ToolCallView[]): string {
  if (!tools.length) return ["tools", row("status", "empty", "no tool calls")].join("\n");
  return ["tools", ...tools.map((tool) => row(toolDisplayName(tool), tool.status, tool.label))].join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}
