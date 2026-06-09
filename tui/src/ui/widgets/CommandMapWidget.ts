import { pickerCommands, type CommandId } from "../../commands";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";
import { makePanelList } from "./panelStyle";

export class CommandMapWidget {
  readonly node: any;
  private intro: any;
  private list: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.intro = makeText(opentui, ctx, {
      content: "commands",
      fg: theme.textMuted,
      flexShrink: 0,
    });
    this.list = makePanelList(opentui, ctx, theme, {
      showDescription: false,
      flexGrow: 1,
      minHeight: 4,
      marginTop: 1,
      itemSpacing: 0,
      maxRows: pickerCommands.length,
      maxTextWidth: 52,
    });
    this.node.add?.(this.intro);
    this.node.add?.(this.list);
    this.update("");
  }

  update(query = ""): void {
    const needle = query.trim().toLowerCase();
    if (this.intro && this.intro.content !== undefined) {
      this.intro.content = needle ? `commands / ${needle}` : "commands";
    }
    if (this.list && "options" in this.list) {
      this.list.options = pickerCommands
        .filter((command) => !needle || command.id.includes(needle) || command.title.toLowerCase().includes(needle))
        .map((command) => ({
          name: `/${command.id}`,
          rightMeta: command.title,
          value: command.id,
        }));
    }
  }

  selectedCommandId(): CommandId | "" {
    return (this.list?.selectedValue?.() ?? "") as CommandId | "";
  }

  moveUp(): boolean {
    return Boolean(this.list?.moveUp?.());
  }

  moveDown(): boolean {
    return Boolean(this.list?.moveDown?.());
  }

  commit(): boolean {
    return Boolean(this.list?.commit?.());
  }
}
