import type { SemanticTokens } from "../../semantic";

// Community theme. Survives but is not in the default cycle (DESIGN_TOKENS.md §5).
export const gruvbox: SemanticTokens = {
  "surface.canvas": "#282828",
  "surface.raised": "#32302f",
  "surface.sunken": "#1d2021",
  "surface.overlay": "#3c3836",
  "surface.modal": "#32302f",

  "border.subtle": "#3c3836",
  "border.strong": "#504945",
  "border.focus": "#fabd2f",
  "border.danger": "#fb4934",

  "text.primary": "#ebdbb2",
  "text.secondary": "#a89984",
  "text.tertiary": "#7c6f64",
  "text.disabled": "#504945",
  "text.on-accent": "#282828",
  "text.on-danger": "#282828",

  "accent.fg": "#fabd2f",
  "accent.soft": "#3a3220",

  "status.success.fg": "#b8bb26",
  "status.success.soft": "#2a3015",
  "status.warning.fg": "#fe8019",
  "status.warning.soft": "#3a2a14",
  "status.danger.fg": "#fb4934",
  "status.danger.soft": "#3a1c19",
  "status.info.fg": "#83a598",
  "status.info.soft": "#1e2e2a",

  "role.user.fg": "#83a598",
  "role.assistant.fg": "#ebdbb2",
  "role.reasoning.fg": "#d3869b",
  "role.tool.idle.fg": "#a89984",
  "role.tool.ok.fg": "#b8bb26",
  "role.tool.fail.fg": "#fb4934",
  "role.system.fg": "#7c6f64",

  "diff.added.bg": "#2a3015",
  "diff.added.fg": "#ebdbb2",
  "diff.removed.bg": "#3a1c19",
  "diff.removed.fg": "#ebdbb2",
  "diff.context.bg": "#1d2021",
  "diff.gutter.fg": "#7c6f64",

  "selection.bg": "#504945",
  "selection.fg": "#ebdbb2",
  "clickable.row.hover.bg": "#46413d",
  "clickable.row.press.bg": "#3a3220",
  "clickable.glyph.hover.fg": "#fabd2f",
  "caret.idle.fg": "#3a3220",
  "caret.stream.fg": "#fabd2f",
};
