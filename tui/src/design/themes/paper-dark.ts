import { chroma, neutralDark } from "../primitives";
import type { SemanticTokens } from "../semantic";

export const paperDark: SemanticTokens = {
  "surface.canvas": neutralDark[900],
  "surface.raised": neutralDark[850],
  "surface.sunken": neutralDark[950],
  "surface.overlay": neutralDark[800],
  "surface.modal": neutralDark[850],

  "border.subtle": neutralDark[700],
  "border.strong": neutralDark[600],
  "border.focus": chroma.brand,
  "border.danger": chroma.danger,

  "text.primary": "#e8eef5",
  "text.secondary": "#9aa4b1",
  "text.tertiary": "#6a7480",
  "text.disabled": neutralDark[500],
  "text.on-accent": neutralDark[950],
  "text.on-danger": neutralDark[950],

  "accent.fg": chroma.brand,
  "accent.soft": "#1a2c4a",

  "status.success.fg": chroma.success,
  "status.success.soft": "#102819",
  "status.warning.fg": chroma.warning,
  "status.warning.soft": "#2e2310",
  "status.danger.fg": chroma.danger,
  "status.danger.soft": "#2e1414",
  "status.info.fg": chroma.info,
  "status.info.soft": "#102622",

  "role.user.fg": chroma.info,
  "role.assistant.fg": "#e8eef5",
  "role.reasoning.fg": chroma.reason,
  "role.tool.idle.fg": "#9aa4b1",
  "role.tool.ok.fg": chroma.success,
  "role.tool.fail.fg": chroma.danger,
  "role.system.fg": "#6a7480",

  "diff.added.bg": "#0e3a1f",
  "diff.added.fg": "#e8eef5",
  "diff.removed.bg": "#3a0e12",
  "diff.removed.fg": "#e8eef5",
  "diff.context.bg": neutralDark[950],
  "diff.gutter.fg": "#6a7480",

  "selection.bg": "#1a2c4a",
  "selection.fg": "#e8eef5",
  "clickable.row.hover.bg": neutralDark[700],
  "clickable.row.press.bg": "#1a2c4a",
  "clickable.glyph.hover.fg": chroma.brand,
  "caret.idle.fg": "#1a2c4a",
  "caret.stream.fg": chroma.brand,
};
