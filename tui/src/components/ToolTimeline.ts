import type { ToolCallView } from "../state/reducer";

export function renderToolTimeline(tools: ToolCallView[]): string {
  if (!tools.length) return "No tool calls.";
  return tools.map((tool) => `${tool.status.padEnd(9)} ${tool.label}`).join("\n");
}
