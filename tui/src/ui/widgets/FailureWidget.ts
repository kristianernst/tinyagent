import type { FailureExplanation } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeSelect, makeText } from "../layout";

export class FailureWidget {
  readonly node: any;
  private summary: any;
  private select: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.summary = makeText(opentui, ctx, { content: "No failure detected.", fg: theme.textMuted });
    this.select = makeSelect(opentui, ctx, {
      options: [],
      showDescription: false,
      backgroundColor: theme.surface,
      textColor: theme.text,
      selectedBackgroundColor: theme.selectionBg,
      selectedTextColor: theme.selectionFg,
      showScrollIndicator: true,
      wrapSelection: true,
      focusable: true,
      flexGrow: 1,
      minHeight: 4,
      marginTop: 1,
    });
    this.node.add?.(this.summary);
    this.node.add?.(this.select);
  }

  update(failure: FailureExplanation | null): void {
    if (!failure) {
      if (this.summary && this.summary.content !== undefined) this.summary.content = "No failure detected in the loaded run.";
      if (this.select && "options" in this.select) this.select.options = [];
      return;
    }
    if (this.summary && this.summary.content !== undefined) {
      this.summary.content = [
        `Source: ${failure.source}`,
        `Last successful event: ${failure.lastSuccessfulEvent}`,
        `Failed event: ${failure.failedEvent}`,
      ].join("\n");
    }
    if (this.select && "options" in this.select) {
      this.select.options = failure.recoveryActions.map((action, index) => ({
        name: action,
        description: "press Enter to copy hint",
        value: String(index),
      }));
    }
  }
}
