import { commands, type CommandId } from "../../commands";
import type { Theme } from "../theme";
import { makeBox, makeSelect, makeText } from "../layout";

export type PaletteSelect = (id: CommandId) => void;

export class PaletteWidget {
  readonly node: any;
  private select: any;
  private query = "";
  private handler: PaletteSelect | null = null;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "rounded",
      border: true,
      borderColor: theme.accent,
      paddingX: 1,
      paddingY: 0,
      backgroundColor: theme.surface,
      title: " Command palette ",
      visible: false,
      position: "absolute",
      top: 2,
      left: 4,
      right: 4,
      maxHeight: 16,
      zIndex: 80,
    });
    this.select = makeSelect(opentui, ctx, {
      options: this.options(""),
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
    });
    this.node.add?.(
      makeText(opentui, ctx, {
        content: "Type to filter. Enter to run. Esc to close.",
        fg: theme.textSubtle,
      }),
    );
    this.node.add?.(this.select);
  }

  show(): void {
    if (this.node && "visible" in this.node) this.node.visible = true;
    this.select?.focus?.();
  }

  hide(): void {
    if (this.node && "visible" in this.node) this.node.visible = false;
    this.select?.blur?.();
    this.query = "";
    this.refresh();
  }

  isVisible(): boolean {
    return Boolean(this.node?.visible);
  }

  setQuery(query: string): void {
    this.query = query;
    this.refresh();
  }

  setOnSelect(handler: PaletteSelect): void {
    if (!this.select) return;
    this.handler = handler;
    const wrapped = (event: any) => {
      const value = event?.value ?? event?.option?.value ?? event?.option?.name;
      if (!value) return;
      handler(value as CommandId);
    };
    if (typeof this.select.on === "function") {
      this.select.on("itemSelected", wrapped);
    }
  }

  moveUp(): void {
    this.select?.moveUp?.(1);
  }

  moveDown(): void {
    this.select?.moveDown?.(1);
  }

  /** Commit the currently highlighted command. Returns true if a command fired. */
  commit(): boolean {
    if (!this.select) return false;
    const handler = this.handler;
    if (typeof this.select.getSelectedOption === "function") {
      const option = this.select.getSelectedOption();
      const value = option?.value as string | undefined;
      if (value && handler) {
        handler(value as any);
        return true;
      }
    }
    if (typeof this.select.selectCurrent === "function") {
      this.select.selectCurrent();
      return true;
    }
    return false;
  }

  private refresh(): void {
    if (!this.select) return;
    if ("options" in this.select) this.select.options = this.options(this.query);
  }

  private options(query: string): Array<{ name: string; description: string; value: string }> {
    const needle = query.replace(/^\//, "").toLowerCase();
    return commands
      .filter((command) => !needle || command.id.includes(needle) || command.title.toLowerCase().includes(needle))
      .map((command) => ({
        name: `/${command.id}`,
        description: command.title,
        value: command.id,
      }));
  }
}
