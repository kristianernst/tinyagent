import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export class ErrorBarWidget {
  readonly node: any;
  private text: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "single",
      border: ["top"],
      borderColor: theme.danger,
      paddingX: 1,
      backgroundColor: theme.surface,
      visible: false,
      flexShrink: 0,
    });
    if (this.node && "enableLayout" in this.node) this.node.enableLayout = false;
    this.text = makeText(opentui, ctx, { content: "", fg: theme.danger });
    this.node.add?.(this.text);
  }

  setErrors(errors: string[]): void {
    const recent = errors.slice(-3);
    const visible = recent.length > 0;
    if (this.node && "visible" in this.node) this.node.visible = visible;
    if (this.node && "enableLayout" in this.node) this.node.enableLayout = visible;
    if (this.text && this.text.content !== undefined) this.text.content = recent.join("\n");
  }
}
