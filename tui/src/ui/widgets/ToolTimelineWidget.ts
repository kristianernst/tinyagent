import type { ToolCallView } from "../../state/reducer";
import { glyphs } from "../../design/glyphs";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";
import { toolDisplayName } from "../toolLabels";
import { makePanelList } from "./panelStyle";

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
    this.select = makePanelList(opentui, ctx, theme, {
      minHeight: 4,
      height: 8,
      flexShrink: 0,
      maxRows: 4,
      maxTextWidth: 52,
    });
    this.detail = makeText(opentui, ctx, {
      content: emptyToolCopy(),
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
      setVisible(this.select, false);
      setFlexGrow(this.node, 0);
      if (this.detail && this.detail.content !== undefined) this.detail.content = emptyToolCopy();
      return;
    }
    setVisible(this.select, true);
    setFlexGrow(this.node, 1);
    if (this.select && "options" in this.select) {
      this.select.options = tools.map((tool) => ({
        name: `${icon(tool.status)} ${toolDisplayName(tool)}`,
        rightMeta: tool.argsSummary?.slice(0, 80) ?? "",
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
      `${icon(tool.status)} ${toolDisplayName(tool)}`,
      row("status", tool.status, tool.label),
      tool.argsSummary ? row("args", tool.argsSummary, "tool input") : "",
      tool.startedAt ? row("started", tool.startedAt, "started at") : "",
      tool.completedAt ? row("completed", tool.completedAt, "completed at") : "",
      tool.output ? `output\n${trimOutput(tool.output)}` : "",
    ].filter(Boolean);
    if (this.detail && this.detail.content !== undefined) this.detail.content = lines.join("\n");
  }
}

function icon(status: string): string {
  if (status === "running") return glyphs.toolRun;
  if (status === "done") return glyphs.toolOk;
  if (status === "failed") return glyphs.toolFail;
  if (status === "blocked") return glyphs.toolBlock;
  if (status === "cancelled") return glyphs.toolSkip;
  return glyphs.system;
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}

function emptyToolCopy(): string {
  return ["tool calls", row("status", "quiet", "waiting for agent actions")].join("\n");
}

function setVisible(node: any, visible: boolean): void {
  if (!node) return;
  if ("visible" in node) node.visible = visible;
  if ("enableLayout" in node) node.enableLayout = visible;
}

function setFlexGrow(node: any, flexGrow: number): void {
  if (node && "flexGrow" in node) node.flexGrow = flexGrow;
}

function trimOutput(output: string): string {
  const limit = 2000;
  if (output.length <= limit) return output;
  return `${output.slice(0, limit)}\n… (+${output.length - limit} bytes)`;
}
