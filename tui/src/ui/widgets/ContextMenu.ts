import type { Theme } from "../theme";
import { makeBox, makeSelect } from "../layout";

export type ContextMenuItem = {
  label: string;
  description?: string;
  value: string;
};

export type ContextMenuSelect = (value: string) => void;

export class ContextMenuWidget {
  readonly node: any;
  private select: any;
  private items: ContextMenuItem[] = [];
  private onPick: ContextMenuSelect | null = null;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "rounded",
      border: true,
      borderColor: theme.accent,
      paddingX: 1,
      paddingY: 0,
      backgroundColor: theme.surface,
      title: " Actions ",
      visible: false,
      position: "absolute",
      zIndex: 100,
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
      showScrollIndicator: false,
      wrapSelection: true,
      focusable: true,
    });
    this.node.add?.(this.select);
    if (typeof this.select?.on === "function") {
      this.select.on("itemSelected", (event: any) => {
        const value = event?.value ?? event?.option?.value;
        if (value && this.onPick) this.onPick(String(value));
        this.hide();
      });
    }
  }

  showAt(x: number, y: number, items: ContextMenuItem[], onPick: ContextMenuSelect): void {
    this.items = items;
    this.onPick = onPick;
    if (this.select && "options" in this.select) {
      this.select.options = items.map((item) => ({
        name: item.label,
        description: item.description ?? "",
        value: item.value,
      }));
    }
    if (this.node && "left" in this.node) this.node.left = Math.max(0, x);
    if (this.node && "top" in this.node) this.node.top = Math.max(0, y);
    if (this.node && "visible" in this.node) this.node.visible = true;
    this.select?.focus?.();
  }

  hide(): void {
    if (this.node && "visible" in this.node) this.node.visible = false;
    this.select?.blur?.();
    this.items = [];
    this.onPick = null;
  }

  isVisible(): boolean {
    return Boolean(this.node?.visible);
  }
}
