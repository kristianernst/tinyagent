import type { AppState } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export class PlanBoardWidget {
  readonly node: any;
  private title: any;
  private body: any;
  private steps: any;

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
      this.title.content = planActive ? "PLAN MODE ACTIVE" : "Build mode";
    }
    if (this.body && this.body.content !== undefined) {
      this.body.content = planActive
        ? "Write tools are locked by backend policy. Use /build to leave plan mode."
        : "Write tools available. Use /plan to switch to planning.";
    }
    // Optional: render plan-step events from latest turn.
    const turn = state.activeSession?.turns.at(-1);
    if (this.steps?.children?.length) {
      for (const child of [...this.steps.children]) this.steps.remove?.(child.id ?? child);
    }
    const planSteps = turn?.tools.filter((tool) => tool.tool === "plan" || tool.tool.startsWith("plan."));
    if (!planSteps?.length) return;
    for (const step of planSteps) {
      this.steps.add?.(
        makeText(this.opentui, this.ctx, {
          content: `${icon(step.status)} ${step.label || step.tool}`,
          fg: colorFor(this.theme, step.status),
        }),
      );
    }
  }
}

function icon(status: string): string {
  if (status === "running") return "•";
  if (status === "done") return "✓";
  if (status === "failed") return "✗";
  return "·";
}

function colorFor(theme: Theme, status: string): string {
  if (status === "done") return theme.success;
  if (status === "failed") return theme.danger;
  if (status === "blocked") return theme.warning;
  return theme.tool;
}
