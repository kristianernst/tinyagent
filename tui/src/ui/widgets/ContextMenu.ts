import { glyphs } from "../../design/glyphs";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";
import { makePanelList } from "./panelStyle";

export type ContextMenuItem = {
  label: string;
  description?: string;
  value: string;
};

export type ContextMenuSelect = (value: string) => void;

export class ContextMenuWidget {
  readonly node: any;
  private select: any;
  private count: any;
  private items: ContextMenuItem[] = [];
  private onPick: ContextMenuSelect | null = null;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "rounded",
      border: true,
      borderColor: theme.borderStrong ?? theme.border,
      paddingX: 0,
      paddingY: 0,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
      visible: false,
      enableLayout: false,
      position: "absolute",
      width: 52,
      maxHeight: 12,
      zIndex: 100,
    });
    const header = makeBox(opentui, ctx, {
      flexDirection: "row",
      height: 1,
      paddingX: 1,
      backgroundColor: theme.surface,
      flexShrink: 0,
    });
    header.add?.(makeText(opentui, ctx, { content: ` ${glyphs.pillL} menu ${glyphs.pillR} actions`, fg: theme.accent, bg: theme.accentSoft }));
    header.add?.(makeBox(opentui, ctx, { flexGrow: 1 }));
    this.count = makeText(opentui, ctx, { content: "", fg: theme.textSubtle });
    header.add?.(this.count);
    this.node.add?.(header);

    this.select = makePanelList(opentui, ctx, theme, {
      showDescription: false,
      itemSpacing: 0,
      height: 3,
      flexShrink: 0,
      maxRows: 3,
      maxTextWidth: 46,
      commitOnClick: true,
    });
    this.node.add?.(this.select);

    const hintWrap = makeBox(opentui, ctx, {
      flexDirection: "column",
      paddingX: 1,
      height: 2,
      flexShrink: 0,
      borderStyle: "single",
      border: ["top"],
      borderColor: theme.border,
    });
    hintWrap.add?.(makeText(opentui, ctx, { content: `${glyphs.kbdL}↑↓${glyphs.kbdR} move   ${glyphs.kbdL}⏎${glyphs.kbdR} choose   ${glyphs.kbdL}esc${glyphs.kbdR} cancel`, fg: theme.textSubtle }));
    this.node.add?.(hintWrap);

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
        rightMeta: menuMeta(item),
        value: item.value,
      }));
    }
    if (this.count && "content" in this.count) this.count.content = items.length ? `${items.length} ` : "";
    if (this.node && "left" in this.node) this.node.left = Math.max(0, x);
    if (this.node && "top" in this.node) this.node.top = Math.max(0, y);
    if (this.node && "visible" in this.node) this.node.visible = true;
    if (this.node && "enableLayout" in this.node) this.node.enableLayout = true;
    this.select?.focus?.();
  }

  hide(): void {
    if (this.node && "visible" in this.node) this.node.visible = false;
    if (this.node && "enableLayout" in this.node) this.node.enableLayout = false;
    this.select?.blur?.();
    this.items = [];
    this.onPick = null;
  }

  isVisible(): boolean {
    return Boolean(this.node?.visible);
  }

  moveUp(): void {
    this.select?.moveUp?.();
  }

  moveDown(): void {
    this.select?.moveDown?.();
  }

  commit(): boolean {
    return Boolean(this.select?.commit?.());
  }
}

function menuMeta(item: ContextMenuItem): string {
  const description = item.description ?? "";
  const known: Record<string, string> = {
    "Copy assistant text to clipboard": "assistant text",
    "Copy assistant text": "assistant text",
    "Copy all turns": "all turns",
    "Cancel active run": "cancel run",
  };
  return known[description] ?? description.toLowerCase();
}
