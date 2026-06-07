import { glyphs } from "../../design/glyphs";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export type HistorySelect = (value: string) => void;

export class HistorySearchWidget {
  readonly node: any;
  private badge: any;
  private title: any;
  private count: any;
  private resultRow: any;
  private result: any;
  private hint: any;
  private query = "";
  private history: string[] = [];
  private matchIndex = 0;
  private callback: HistorySelect | null = null;

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
      bottom: 6,
      left: 2,
      width: 72,
      minWidth: 42,
      maxWidth: 72,
      minHeight: 5,
      maxHeight: 7,
      zIndex: 75,
    });
    const header = makeBox(opentui, ctx, {
      flexDirection: "row",
      height: 1,
      paddingX: 1,
      backgroundColor: theme.surface,
      flexShrink: 0,
    });
    this.badge = makeText(opentui, ctx, {
      content: ` ${glyphs.pillL} ^R ${glyphs.pillR} `,
      fg: theme.accent,
      bg: theme.accentSoft,
    });
    header.add?.(this.badge);
    this.title = makeText(opentui, ctx, { content: " history", fg: theme.textMuted, marginLeft: 1 });
    header.add?.(this.title);
    header.add?.(makeBox(opentui, ctx, { flexGrow: 1 }));
    this.count = makeText(opentui, ctx, { content: "", fg: theme.textSubtle });
    header.add?.(this.count);
    this.node.add?.(header);

    this.resultRow = makeBox(opentui, ctx, {
      flexDirection: "row",
      height: 1,
      paddingX: 1,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
      flexShrink: 0,
    });
    this.result = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.resultRow.add?.(this.result);
    this.node.add?.(this.resultRow);

    const hintWrap = makeBox(opentui, ctx, {
      flexDirection: "column",
      paddingX: 1,
      flexShrink: 0,
      borderStyle: "single",
      border: ["top"],
      borderColor: theme.border,
    });
    this.hint = makeText(opentui, ctx, { content: hintLine(), fg: theme.textSubtle });
    hintWrap.add?.(this.hint);
    this.node.add?.(hintWrap);
  }

  open(history: string[], onPick: HistorySelect): void {
    this.history = history.slice();
    this.query = "";
    this.matchIndex = 0;
    this.callback = onPick;
    if (this.node && "visible" in this.node) this.node.visible = true;
    if (this.node && "enableLayout" in this.node) this.node.enableLayout = true;
    this.refresh();
  }

  close(): void {
    if (this.node && "visible" in this.node) this.node.visible = false;
    if (this.node && "enableLayout" in this.node) this.node.enableLayout = false;
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
    const matches = this.matches();
    if (!matches.length) return null;
    const cursor = this.matchIndex % matches.length;
    return matches[cursor] ?? null;
  }

  private matches(): string[] {
    if (!this.query) return [];
    return this.history
      .map((entry) => ({ entry }))
      .filter((row) => row.entry.toLowerCase().includes(this.query.toLowerCase()))
      .reverse()
      .map((row) => row.entry);
  }

  private refresh(): void {
    const matches = this.matches();
    const match = this.currentMatch();
    if (this.count && this.count.content !== undefined) {
      this.count.content = matches.length > 0 ? `${(this.matchIndex % matches.length) + 1}/${matches.length} ` : "";
    }
    if (this.title && this.title.content !== undefined) {
      this.title.content = this.query ? ` history · ${fitText(this.query, 42)}` : " history";
    }
    if (this.resultRow && "backgroundColor" in this.resultRow) {
      this.resultRow.backgroundColor = match ? this.theme.selectionBg : (this.theme.surfaceOverlay ?? this.theme.surface);
    }
    if (this.result && this.result.content !== undefined) {
      this.result.fg = match ? this.theme.text : this.theme.textSubtle;
      this.result.content = match ? `${glyphs.chevron} ${fitText(match, 64)}` : this.query ? "no matches" : "recent commands";
    }
  }
}

function hintLine(): string {
  return `type to filter   ${glyphs.kbdL}^R${glyphs.kbdR} next   ${glyphs.kbdL}⏎${glyphs.kbdR} use   ${glyphs.kbdL}esc${glyphs.kbdR} cancel`;
}

function fitText(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, Math.max(0, max - 1))}…`;
}
