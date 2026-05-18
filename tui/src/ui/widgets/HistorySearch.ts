import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export type HistorySelect = (value: string) => void;

export class HistorySearchWidget {
  readonly node: any;
  private label: any;
  private result: any;
  private query = "";
  private history: string[] = [];
  private matchIndex = 0;
  private callback: HistorySelect | null = null;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "rounded",
      border: true,
      borderColor: theme.accent,
      paddingX: 1,
      paddingY: 0,
      backgroundColor: theme.surfaceMuted,
      title: " reverse-i-search ",
      visible: false,
      position: "absolute",
      bottom: 6,
      left: 4,
      right: 4,
      maxHeight: 5,
      zIndex: 70,
    });
    this.label = makeText(opentui, ctx, { content: "(reverse-i-search): ", fg: theme.textMuted });
    this.result = makeText(opentui, ctx, { content: "", fg: theme.text });
    this.node.add?.(this.label);
    this.node.add?.(this.result);
  }

  open(history: string[], onPick: HistorySelect): void {
    this.history = history.slice();
    this.query = "";
    this.matchIndex = 0;
    this.callback = onPick;
    if (this.node && "visible" in this.node) this.node.visible = true;
    this.refresh();
  }

  close(): void {
    if (this.node && "visible" in this.node) this.node.visible = false;
    this.query = "";
    this.history = [];
    this.matchIndex = 0;
    this.callback = null;
  }

  isOpen(): boolean {
    return Boolean(this.node?.visible);
  }

  appendChar(ch: string): void {
    this.query += ch;
    this.matchIndex = 0;
    this.refresh();
  }

  backspace(): void {
    this.query = this.query.slice(0, -1);
    this.matchIndex = 0;
    this.refresh();
  }

  cycle(): void {
    this.matchIndex += 1;
    this.refresh();
  }

  commit(): string | null {
    const match = this.currentMatch();
    if (match && this.callback) this.callback(match);
    this.close();
    return match;
  }

  private currentMatch(): string | null {
    if (!this.query) return null;
    const matches = this.history
      .map((entry, index) => ({ entry, index }))
      .filter((row) => row.entry.toLowerCase().includes(this.query.toLowerCase()))
      .reverse();
    if (!matches.length) return null;
    const cursor = this.matchIndex % matches.length;
    return matches[cursor]?.entry ?? null;
  }

  private refresh(): void {
    if (this.label && this.label.content !== undefined) {
      this.label.content = `(reverse-i-search) "${this.query}": `;
    }
    const match = this.currentMatch();
    if (this.result && this.result.content !== undefined) {
      this.result.content = match ?? (this.query ? "(no match)" : "");
    }
  }
}
