import type { ToolCallView } from "../state/reducer";

export function toolDisplayName(tool: ToolCallView): string {
  const rawTool = tool.tool.trim();
  const label = tool.label.trim();
  if (label && label !== rawTool && !startsWithToolName(label, rawTool)) {
    return firstWord(label);
  }
  return firstWord(rawTool.replace(/[._-]+/g, " ")) || "tool";
}

export function toolLaneName(tool: ToolCallView, width: number): string {
  const name = toolDisplayName(tool);
  if (name.length <= width) return name.padEnd(width);
  if (width <= 1) return name.slice(0, width);
  return `${name.slice(0, width - 1)}…`;
}

function startsWithToolName(label: string, tool: string): boolean {
  return label.toLowerCase().startsWith(`${tool.toLowerCase()} `);
}

function firstWord(value: string): string {
  return value.trim().split(/\s+/)[0] ?? "";
}
