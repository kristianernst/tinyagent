import { glyphs } from "../../design/glyphs";
import type { DiffState } from "../../state/reducer";
import { makeBox, makeDiff } from "../layout";
import type { Theme } from "../theme";
import { InfoPanelWidget, type InfoPanelRow } from "./InfoPanelWidget";

export class DiffWidget {
  readonly node: any;
  private summary: InfoPanelWidget;
  private diffNode: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme, syntaxStyle?: any) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      flexGrow: 1,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
    });
    this.summary = new InfoPanelWidget(opentui, ctx, theme, { compact: true, minHeight: 9 });
    this.diffNode = makeDiff(opentui, ctx, {
      diff: "",
      view: "unified",
      showLineNumbers: true,
      syntaxStyle,
      flexGrow: 1,
      marginTop: 1,
    });
    this.node.add?.(this.summary.node);
    this.node.add?.(this.diffNode);
  }

  update(diff: DiffState | null, view: "unified" | "split" = "unified"): void {
    this.summary.update({
      eyebrow: "diff summary",
      rows: diffRows(diff, view),
    });
    const text = diff?.text ?? "";
    if (this.diffNode && "diff" in this.diffNode) this.diffNode.diff = text;
    else if (this.diffNode && "content" in this.diffNode) this.diffNode.content = text;
    if (this.diffNode && "view" in this.diffNode) this.diffNode.view = view;
  }
}

function diffRows(diff: DiffState | null, view: "unified" | "split"): InfoPanelRow[] {
  if (!diff) {
    return [{ label: "status", value: "empty", detail: "no changes", tone: "muted" }];
  }

  if (!diff.text) {
    const rows: InfoPanelRow[] = [
      {
        label: "status",
        value: diff.omittedFiles ? "private only" : "empty",
        detail: diff.omittedFiles ? omittedDetail(diff.omittedFiles) : "no changes",
        tone: diff.omittedFiles ? "warning" : "muted",
      },
      { label: "display", value: "empty", detail: "no text diff available" },
    ];
    return rows;
  }

  const counts = diffCounts(diff.text);
  const rows: InfoPanelRow[] = [
    {
      label: "files",
      value: diff.paths.length ? unit(diff.paths.length, "changed file") : "available",
      detail: pathDetail(diff.paths),
      tone: "accent",
    },
    {
      label: "changes",
      value: `+${counts.added} ${glyphs.minus}${counts.removed}`,
      detail: `${view} · ${diff.truncated ? "truncated" : "full patch"}`,
    },
  ];
  if (diff.omittedFiles) {
    rows.push({ label: "omitted", value: String(diff.omittedFiles), detail: omittedDetail(diff.omittedFiles), tone: "warning" });
  }
  return rows;
}

function diffCounts(text: string): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of text.split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) added += 1;
    else if (line.startsWith("-")) removed += 1;
  }
  return { added, removed };
}

function pathDetail(paths: string[]): string {
  if (!paths.length) return "paths unavailable";
  return paths.map((path) => path.split("/").pop() ?? path).join(" · ");
}

function omittedDetail(count: number): string {
  return `${unit(count, "private file")} omitted`;
}

function unit(count: number, label: string): string {
  return `${count} ${label}${count === 1 ? "" : "s"}`;
}
