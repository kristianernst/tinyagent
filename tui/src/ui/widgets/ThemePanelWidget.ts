import { glyphs } from "../../design/glyphs";
import { spinnerFrame } from "../../design/spinners";
import type { AppState } from "../../state/reducer";
import { makeBox, makeText } from "../layout";
import { resolveTheme, themeNames, type Theme } from "../theme";

const PREVIEW_DIVIDER_WIDTH = 34;

export class ThemePanelWidget {
  readonly node: any;
  private cardsNode: any;
  private cards: any[] = [];

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      flexGrow: 1,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
    });
    this.node.add?.(
      makeText(opentui, ctx, {
        content: "same widgets · different semantic tokens",
        fg: theme.textMuted,
        flexShrink: 0,
      }),
    );
    this.cardsNode = makeBox(opentui, ctx, {
      flexDirection: "column",
      flexGrow: 1,
      marginTop: 1,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
    });
    this.node.add?.(this.cardsNode);
  }

  update(state: AppState): void {
    const activeTheme = state.ui.theme || state.settings.theme;
    this.clearCards();
    for (const name of themeNames) this.addCard(name, name === activeTheme);
  }

  private clearCards(): void {
    for (const card of this.cards.splice(0)) this.cardsNode.remove?.(card.id ?? card);
  }

  private addCard(name: string, active: boolean): void {
    const preview = resolveTheme(name);
    const card = makeBox(this.opentui, this.ctx, {
      flexDirection: "column",
      borderStyle: "rounded",
      border: true,
      borderColor: active ? preview.borderFocus : this.theme.borderStrong ?? this.theme.border,
      paddingX: 1,
      paddingY: 0,
      marginBottom: 0,
      backgroundColor: preview.surface,
      flexShrink: 0,
    });

    const header = makeBox(this.opentui, this.ctx, {
      flexDirection: "row",
      height: 1,
      backgroundColor: preview.surface,
      flexShrink: 0,
    });
    const meta = themeMeta(name);
    header.add?.(
      makeText(this.opentui, this.ctx, {
        content: `  ${meta.label}`,
        fg: active ? preview.accent : preview.text,
      }),
    );
    header.add?.(
      makeText(this.opentui, this.ctx, {
        content: ` ${meta.subtitle}`,
        fg: preview.textSubtle,
        marginLeft: 1,
      }),
    );
    card.add?.(header);

    card.add?.(previewRow(this.opentui, this.ctx, preview, glyphs.chevron, "apply the patch and rerun tests", preview.user));
    card.add?.(previewRow(this.opentui, this.ctx, preview, glyphs.bulletDiamond, "thought for 2s", preview.reasoning));
    card.add?.(previewRow(this.opentui, this.ctx, preview, glyphs.toolOk, `edit Transcript.ts · +3 ${glyphs.minus}1`, preview.toolOk));
    card.add?.(previewRow(this.opentui, this.ctx, preview, spinnerFrame("braille", 1), "shell bun test", preview.toolIdle));
    card.add?.(makeText(this.opentui, this.ctx, { content: glyphs.dividerThin.repeat(PREVIEW_DIVIDER_WIDTH), fg: preview.border }));
    card.add?.(makeText(this.opentui, this.ctx, { content: ` ${glyphs.caretIdle} implement design tokens`, fg: preview.text, bg: preview.surfaceMuted }));

    this.cardsNode.add?.(card);
    this.cards.push(card);
  }
}

function previewRow(opentui: any, ctx: any, theme: Theme, marker: string, label: string, fg: string): any {
  const row = makeBox(opentui, ctx, {
    flexDirection: "row",
    height: 1,
    backgroundColor: theme.surface,
    flexShrink: 0,
  });
  row.add?.(
    makeText(opentui, ctx, {
      content: marker.padEnd(2),
      fg,
      flexShrink: 0,
    }),
  );
  row.add?.(makeText(opentui, ctx, { content: label, fg }));
  return row;
}

function themeMeta(name: string): { label: string; subtitle: string } {
  if (name === "paper-dark") return { label: "PAPER-DARK", subtitle: "default" };
  if (name === "paper-light") return { label: "PAPER-LIGHT", subtitle: "bright environments" };
  if (name === "mono") return { label: "MONO", subtitle: "screen recording · demos · CI snapshots" };
  return { label: name.toUpperCase(), subtitle: "custom" };
}
