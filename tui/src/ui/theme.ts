// Bridge layer: maps the new semantic-token system (tui/src/design/) onto the
// flat `Theme` shape widgets consume. When a widget needs a new role, add it
// to the semantic tokens and surface it here. Widgets do not import primitives
// or theme files directly.
//
// See tui/DESIGN_TOKENS.md §1 for the layer model.

import type { SemanticTokens } from "../design/semantic";
import { paperDark } from "../design/themes/paper-dark";
import { paperLight } from "../design/themes/paper-light";
import { mono } from "../design/themes/mono";
import { highContrast } from "../design/themes/high-contrast";
import { dracula } from "../design/themes/community/dracula";
import { gruvbox } from "../design/themes/community/gruvbox";

export type Theme = {
  name: string;
  background: string;
  surface: string;
  surfaceMuted: string;
  border: string;
  borderFocus: string;
  text: string;
  textMuted: string;
  textSubtle: string;
  accent: string;
  success: string;
  warning: string;
  danger: string;
  info: string;
  selectionBg: string;
  selectionFg: string;
  rowHoverBg: string;
  rowPressBg: string;
  rowHoverFg: string;
  user: string;
  assistant: string;
  reasoning: string;
  tool: string;
  diffAdded: string;
  diffRemoved: string;
  diffContext: string;
  spinner: string;
  cursorBg: string;
  cursorFg: string;

  // Extended slots for the new chrome bar / picker / overlay surfaces.
  surfaceOverlay: string;
  surfaceModal: string;
  borderStrong: string;
  borderDanger: string;
  accentSoft: string;
  successSoft: string;
  warningSoft: string;
  dangerSoft: string;
  infoSoft: string;
  toolIdle: string;
  toolOk: string;
  toolFail: string;
  caretIdle: string;
  caretStream: string;
};

function compose(name: string, tokens: SemanticTokens): Theme {
  return {
    name,
    background: tokens["surface.canvas"],
    surface: tokens["surface.raised"],
    surfaceMuted: tokens["surface.sunken"],
    border: tokens["border.subtle"],
    borderFocus: tokens["border.focus"],
    text: tokens["text.primary"],
    textMuted: tokens["text.secondary"],
    textSubtle: tokens["text.tertiary"],
    accent: tokens["accent.fg"],
    success: tokens["status.success.fg"],
    warning: tokens["status.warning.fg"],
    danger: tokens["status.danger.fg"],
    info: tokens["status.info.fg"],
    selectionBg: tokens["selection.bg"],
    selectionFg: tokens["selection.fg"],
    rowHoverBg: tokens["clickable.row.hover.bg"],
    rowPressBg: tokens["clickable.row.press.bg"],
    rowHoverFg: tokens["clickable.glyph.hover.fg"],
    user: tokens["role.user.fg"],
    assistant: tokens["role.assistant.fg"],
    reasoning: tokens["role.reasoning.fg"],
    tool: tokens["role.tool.idle.fg"],
    diffAdded: tokens["diff.added.bg"],
    diffRemoved: tokens["diff.removed.bg"],
    diffContext: tokens["diff.context.bg"],
    spinner: tokens["role.tool.idle.fg"],
    cursorBg: tokens["caret.stream.fg"],
    cursorFg: tokens["surface.canvas"],

    surfaceOverlay: tokens["surface.overlay"],
    surfaceModal: tokens["surface.modal"],
    borderStrong: tokens["border.strong"],
    borderDanger: tokens["border.danger"],
    accentSoft: tokens["accent.soft"],
    successSoft: tokens["status.success.soft"],
    warningSoft: tokens["status.warning.soft"],
    dangerSoft: tokens["status.danger.soft"],
    infoSoft: tokens["status.info.soft"],
    toolIdle: tokens["role.tool.idle.fg"],
    toolOk: tokens["role.tool.ok.fg"],
    toolFail: tokens["role.tool.fail.fg"],
    caretIdle: tokens["caret.idle.fg"],
    caretStream: tokens["caret.stream.fg"],
  };
}

const paperDarkTheme = compose("paper-dark", paperDark);
const paperLightTheme = compose("paper-light", paperLight);
const monoTheme = compose("mono", mono);
const highContrastTheme = compose("high-contrast", highContrast);
const draculaTheme = compose("dracula", dracula);
const gruvboxTheme = compose("gruvbox", gruvbox);

// Back-compat aliases — old configs and tests persist these names. The aliased
// theme keeps the requested `name` field so `resolveTheme("tiny-dark").name ===
// "tiny-dark"`; everything else is paper-dark / paper-light values.
const tinyDarkAlias: Theme = { ...paperDarkTheme, name: "tiny-dark" };
const tinyLightAlias: Theme = { ...paperLightTheme, name: "tiny-light" };

export const themes: Record<string, Theme> = {
  "paper-dark": paperDarkTheme,
  "paper-light": paperLightTheme,
  mono: monoTheme,
  "high-contrast": highContrastTheme,
  dracula: draculaTheme,
  gruvbox: gruvboxTheme,
  "tiny-dark": tinyDarkAlias,
  "tiny-light": tinyLightAlias,
};

export function resolveTheme(name: string | undefined): Theme {
  return themes[name ?? ""] ?? paperDarkTheme;
}

// The default cycle is the three first-party themes. Community themes are
// reachable via `/theme dracula`, `/theme gruvbox`; high-contrast is opt-in
// from settings. Keep /theme aligned with the three preview cards in Paper.
export const themeNames = ["paper-dark", "paper-light", "mono"];
export const selectableThemeNames = [...themeNames, "high-contrast"];
