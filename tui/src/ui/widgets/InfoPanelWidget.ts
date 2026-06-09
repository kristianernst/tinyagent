import { glyphs } from "../../design/glyphs";
import { makeBox, makeText } from "../layout";
import type { Theme } from "../theme";

export type InfoPanelTone = "default" | "accent" | "success" | "warning" | "danger" | "muted";

export type InfoPanelRow = {
  label: string;
  value: string;
  detail?: string;
  tone?: InfoPanelTone;
};

export type InfoPanelContent = {
  eyebrow: string;
  rows: InfoPanelRow[];
  footer?: string;
};

export type InfoPanelOptions = {
  compact?: boolean;
  minHeight?: number;
};

export class InfoPanelWidget {
  readonly node: any;
  private eyebrow: any;
  private rowsNode: any;
  private footer: any;
  private rowNodes: any[] = [];

  constructor(private opentui: any, private ctx: any, private theme: Theme, options: InfoPanelOptions = {}) {
    const flexGrow = options.compact ? 0 : 1;
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      flexGrow,
      flexShrink: 0,
      minHeight: options.minHeight ?? (options.compact ? 13 : undefined),
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
    });
    this.eyebrow = makeText(opentui, ctx, {
      content: "",
      fg: theme.textMuted,
      flexShrink: 0,
    });
    this.rowsNode = makeBox(opentui, ctx, {
      flexDirection: "column",
      flexGrow,
      flexShrink: 0,
      marginTop: 1,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
    });
    this.footer = makeText(opentui, ctx, {
      content: "",
      fg: theme.textSubtle,
      marginTop: 1,
      flexShrink: 0,
    });
    this.node.add?.(this.eyebrow);
    this.node.add?.(this.rowsNode);
    this.node.add?.(this.footer);
  }

  update(content: InfoPanelContent): void {
    if (this.eyebrow && this.eyebrow.content !== undefined) this.eyebrow.content = content.eyebrow;
    this.clearRows();
    for (const row of content.rows) this.addRow(row);
    const hasFooter = Boolean(content.footer);
    if (this.footer && this.footer.content !== undefined) this.footer.content = truncate(content.footer ?? "", 50);
    if (this.footer && "visible" in this.footer) this.footer.visible = hasFooter;
    if (this.footer && "enableLayout" in this.footer) this.footer.enableLayout = hasFooter;
  }

  private clearRows(): void {
    for (const row of this.rowNodes.splice(0)) this.rowsNode.remove?.(row.id ?? row);
  }

  private addRow(row: InfoPanelRow): void {
    const tone = row.tone ?? "default";
    const line = makeBox(this.opentui, this.ctx, {
      flexDirection: "row",
      alignItems: "center",
      minHeight: 1,
      backgroundColor: tone === "accent" ? this.theme.accentSoft : this.theme.surfaceOverlay ?? this.theme.surface,
    });
    const wrap = makeBox(this.opentui, this.ctx, {
      flexDirection: "column",
      minHeight: row.detail ? 3 : 2,
      paddingX: 1,
      paddingY: 0,
      borderStyle: "single",
      border: ["bottom"],
      borderColor: this.theme.borderStrong ?? this.theme.border,
      backgroundColor: tone === "accent" ? this.theme.accentSoft : this.theme.surfaceOverlay ?? this.theme.surface,
    });
    line.add?.(
      makeText(this.opentui, this.ctx, {
        content: glyphs.caretIdle,
        fg: toneColor(tone, this.theme),
        width: 2,
      }),
    );
    line.add?.(
      makeText(this.opentui, this.ctx, {
        content: truncate(row.label.toLowerCase(), 13),
        fg: tone === "muted" ? this.theme.textSubtle : this.theme.textMuted,
        width: 15,
      }),
    );
    line.add?.(
      makeText(this.opentui, this.ctx, {
        content: truncate(row.value, 31),
        fg: tone === "muted" ? this.theme.textMuted : this.theme.text,
      }),
    );
    wrap.add?.(line);
    if (row.detail) {
      wrap.add?.(
        makeText(this.opentui, this.ctx, {
          content: `  ${truncate(row.detail, 58)}`,
          fg: this.theme.textSubtle,
        }),
      );
    }
    this.rowsNode.add?.(wrap);
    this.rowNodes.push(wrap);
  }
}

function toneColor(tone: InfoPanelTone, theme: Theme): string {
  if (tone === "accent") return theme.accent;
  if (tone === "success") return theme.success;
  if (tone === "warning") return theme.warning;
  if (tone === "danger") return theme.danger;
  return theme.textSubtle;
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, Math.max(0, max - 1))}…`;
}
