import type { EvalLabState } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeSelect, makeText } from "../layout";

export class EvalLabWidget {
  readonly node: any;
  private header: any;
  private select: any;
  private report: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.header = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
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
      marginTop: 1,
    });
    this.report = makeText(opentui, ctx, { content: "", fg: theme.assistant, marginTop: 1 });
    this.node.add?.(this.header);
    this.node.add?.(this.select);
    this.node.add?.(this.report);
  }

  update(evalLab: EvalLabState): void {
    if (this.header && this.header.content !== undefined) {
      this.header.content = [
        `Status: ${evalLab.status}`,
        evalLab.suitePath ? `Suite: ${evalLab.suitePath}` : "",
        evalLab.outputDir ? `Output: ${evalLab.outputDir}` : "",
        evalLab.command ? `CLI: ${evalLab.command}` : "",
        evalLab.error ? `Error: ${evalLab.error}` : "",
      ]
        .filter(Boolean)
        .join("\n");
    }
    if (this.select && "options" in this.select) {
      this.select.options = evalLab.results.map((result) => ({
        name: `${result.success ? "✓" : "✗"} ${result.case_id}`,
        description: result.status + (result.failure_reason ? ` — ${result.failure_reason}` : ""),
        value: result.case_id,
      }));
    }
    if (this.report && this.report.content !== undefined) {
      const text = evalLab.report?.split("\n").slice(0, 24).join("\n") ?? "";
      this.report.content = text;
    }
  }
}
