import type { AppState } from "../../state/reducer";
import { glyphs } from "../../design/glyphs";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export class PlanBoardWidget {
  readonly node: any;
  private title: any;
  private body: any;
  private steps: any;
  private stepRows: any[] = [];

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
    });
    this.title = makeText(opentui, ctx, { content: "", fg: theme.reasoning });
    this.body = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.steps = makeBox(opentui, ctx, { flexDirection: "column", marginTop: 1 });
    this.node.add?.(this.title);
    this.node.add?.(this.body);
    this.node.add?.(this.steps);
  }

  update(state: AppState): void {
    const planActive = state.sessionMode === "plan";
    if (this.title && this.title.content !== undefined) {
      this.title.content = "session mode";
    }
    if (this.body && this.body.content !== undefined) {
      this.body.content = planActive ? row("mode", "plan", "write tools locked") : row("mode", "build", "write tools available");
    }
    // Optional: render plan-step events from latest turn.
    const turn = state.activeSession?.turns.at(-1);
    const planSteps = turn?.tools.filter((tool) => tool.tool === "plan" || tool.tool.startsWith("plan."));
    const count = planSteps?.length ?? 0;
    while (this.stepRows.length < count) {
      const node = makeText(this.opentui, this.ctx, { content: "", fg: this.theme.tool });
      this.stepRows.push(node);
      this.steps.add?.(node);
    }
    for (let index = 0; index < this.stepRows.length; index += 1) {
      const node = this.stepRows[index];
      const step = planSteps?.[index];
      const show = Boolean(step);
      if (node && "visible" in node) node.visible = show;
      if (node && "enableLayout" in node) node.enableLayout = show;
      if (!node || node.content === undefined) continue;
      node.content = step ? `${icon(step.status)} ${step.label || step.tool}` : "";
      node.fg = step ? colorFor(this.theme, step.status) : this.theme.tool;
    }
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

function colorFor(theme: Theme, status: string): string {
  if (status === "done") return theme.success;
  if (status === "failed") return theme.danger;
  if (status === "blocked") return theme.warning;
  return theme.tool;
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}
