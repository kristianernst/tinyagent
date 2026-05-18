import type { ToolCallView } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeSelect, makeText } from "../layout";

export class ToolTimelineWidget {
  readonly node: any;
  private select: any;
  private detail: any;
  private tools: ToolCallView[] = [];

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      flexGrow: 1,
    });
    this.select = makeSelect(opentui, ctx, {
      options: [],
      showDescription: true,
      backgroundColor: theme.surface,
      textColor: theme.text,
      selectedBackgroundColor: theme.selectionBg,
      selectedTextColor: theme.selectionFg,
      descriptionColor: theme.textMuted,
      selectedDescriptionColor: theme.text,
      showScrollIndicator: true,
      wrapSelection: true,
      focusable: true,
      flexGrow: 1,
      minHeight: 4,
    });
    this.detail = makeText(opentui, ctx, {
      content: "No tool selected.",
      fg: theme.textMuted,
      marginTop: 1,
    });
    this.node.add?.(this.select);
    this.node.add?.(this.detail);
    if (typeof this.select?.on === "function") {
      this.select.on("selectionChanged", (event: any) => {
        const index = event?.index ?? event?.selectedIndex ?? 0;
        this.renderDetail(this.tools[index]);
      });
    }
  }

  update(tools: ToolCallView[]): void {
    this.tools = tools;
    if (!tools.length) {
      if (this.select && "options" in this.select) this.select.options = [];
      if (this.detail && this.detail.content !== undefined) this.detail.content = "No tool calls yet.";
      return;
    }
    if (this.select && "options" in this.select) {
      this.select.options = tools.map((tool) => ({
        name: `${icon(tool.status)} ${tool.tool}`,
        description: tool.argsSummary?.slice(0, 80) ?? "",
        value: tool.id,
      }));
    }
    const head = this.tools[0];
    this.renderDetail(head);
  }

  private renderDetail(tool: ToolCallView | undefined): void {
    if (!tool) {
      if (this.detail && this.detail.content !== undefined) this.detail.content = "";
      return;
    }
    const lines = [
      `${icon(tool.status)} ${tool.tool}  ·  status: ${tool.status}`,
      tool.argsSummary ? `args: ${tool.argsSummary}` : "",
      tool.startedAt ? `started: ${tool.startedAt}` : "",
      tool.completedAt ? `completed: ${tool.completedAt}` : "",
      tool.output ? `\n${trimOutput(tool.output)}` : "",
    ].filter(Boolean);
    if (this.detail && this.detail.content !== undefined) this.detail.content = lines.join("\n");
  }
}

function icon(status: string): string {
  if (status === "running") return "•";
  if (status === "done") return "✓";
  if (status === "failed") return "✗";
  if (status === "blocked") return "■";
  if (status === "cancelled") return "○";
  return "·";
}

function trimOutput(output: string): string {
  const limit = 2000;
  if (output.length <= limit) return output;
  return `${output.slice(0, limit)}\n… (+${output.length - limit} bytes)`;
}
