import type { EvalLabState } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";
import { InfoPanelWidget } from "./InfoPanelWidget";
import { makePanelList } from "./panelStyle";

export class EvalLabWidget {
  readonly node: any;
  private header: InfoPanelWidget;
  private select: any;
  private footer: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.header = new InfoPanelWidget(opentui, ctx, theme, { compact: true, minHeight: 11 });
    this.select = makePanelList(opentui, ctx, theme, {
      showDescription: true,
      minHeight: 4,
      height: 8,
      flexShrink: 0,
      marginTop: 1,
      maxRows: 4,
    });
    this.footer = makeText(opentui, ctx, { content: "", fg: theme.textSubtle, marginTop: 1 });
    this.node.add?.(this.header.node);
    this.node.add?.(this.select);
    this.node.add?.(this.footer);
  }

  update(evalLab: EvalLabState): void {
    this.header.update({
      eyebrow: "eval lab",
      rows: [
        {
          label: "status",
          value: evalLab.status,
          detail: evalStatusDetail(evalLab),
          tone: evalTone(evalLab.status),
        },
        {
          label: "suite",
          value: evalLab.suitePath || "not selected",
          detail: evalSuiteDetail(evalLab),
        },
        {
          label: "output",
          value: evalLab.outputDir ? "eval artifacts" : "not available",
          detail: evalLab.error || evalLab.outputDir || `${evalLab.results.length} case${evalLab.results.length === 1 ? "" : "s"} loaded`,
          tone: evalLab.error ? "danger" : "default",
        },
      ],
    });
    if (this.select && "options" in this.select) {
      this.select.options = evalLab.results.map((result) => ({
        name: result.case_id,
        rightMeta: result.status,
        description: result.failure_reason || "",
        value: result.case_id,
      }));
    }
    if (this.footer && this.footer.content !== undefined) {
      this.footer.content = evalFooter(evalLab);
    }
  }
}

function evalTone(status: EvalLabState["status"]) {
  if (status === "completed") return "success";
  if (status === "running") return "accent";
  if (status === "failed") return "danger";
  return "muted";
}

function evalStatusDetail(evalLab: EvalLabState): string {
  if (evalLab.error) return evalLab.error;
  if (evalLab.status === "completed") {
    const passed = evalLab.results.filter((result) => result.success).length;
    return `${passed} / ${evalLab.results.length} passing`;
  }
  if (evalLab.status === "running") return "suite is currently executing";
  return "no active eval run";
}

function evalSuiteDetail(evalLab: EvalLabState): string {
  return evalLab.suitePath ? "snapshot gate" : "choose a suite";
}

function evalFooter(evalLab: EvalLabState): string {
  if (evalLab.error) return `needs attention · ${evalLab.error}`;
  if (evalLab.status === "running") return `running · ${evalLab.results.length} case${evalLab.results.length === 1 ? "" : "s"} loaded`;
  if (evalLab.status !== "completed") return "waiting for suite";
  const failed = evalLab.results.filter((result) => !result.success);
  if (!failed.length) return "all cases passing";
  const first = failed[0]!;
  return `needs review · ${first.case_id}${first.failure_reason ? ` · ${compactReason(first.failure_reason)}` : ""}`;
}

function compactReason(reason: string): string {
  return reason.replace(/\s+at\s+\d+\s+columns?\b/i, "");
}
