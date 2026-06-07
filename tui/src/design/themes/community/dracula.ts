import type { SemanticTokens } from "../../semantic";

// Community theme. Survives but is not in the default cycle (DESIGN_TOKENS.md §5).
// Users can opt in via /theme dracula or settings.json.
export const dracula: SemanticTokens = {
  "surface.canvas": "#282a36",
  "surface.raised": "#21222c",
  "surface.sunken": "#191a21",
  "surface.overlay": "#21222c",
  "surface.modal": "#21222c",

  "border.subtle": "#3a3c4a",
  "border.strong": "#44475a",
  "border.focus": "#bd93f9",
  "border.danger": "#ff5555",

  "text.primary": "#f8f8f2",
  "text.secondary": "#a89bca",
  "text.tertiary": "#6272a4",
  "text.disabled": "#44475a",
  "text.on-accent": "#282a36",
  "text.on-danger": "#282a36",

  "accent.fg": "#bd93f9",
  "accent.soft": "#3d3057",

  "status.success.fg": "#50fa7b",
  "status.success.soft": "#1f3a2a",
  "status.warning.fg": "#f1fa8c",
  "status.warning.soft": "#3a3a1f",
  "status.danger.fg": "#ff5555",
  "status.danger.soft": "#3a1f1f",
  "status.info.fg": "#8be9fd",
  "status.info.soft": "#1f3a3a",

  "role.user.fg": "#8be9fd",
  "role.assistant.fg": "#f8f8f2",
  "role.reasoning.fg": "#bd93f9",
  "role.tool.idle.fg": "#a89bca",
  "role.tool.ok.fg": "#50fa7b",
  "role.tool.fail.fg": "#ff5555",
  "role.system.fg": "#6272a4",

  "diff.added.bg": "#1f3a2a",
  "diff.added.fg": "#f8f8f2",
  "diff.removed.bg": "#3a1f1f",
  "diff.removed.fg": "#f8f8f2",
  "diff.context.bg": "#191a21",
  "diff.gutter.fg": "#6272a4",

  "selection.bg": "#44475a",
  "selection.fg": "#f8f8f2",
  "clickable.row.hover.bg": "#282a36",
  "clickable.row.press.bg": "#3d3057",
  "clickable.glyph.hover.fg": "#bd93f9",
  "caret.idle.fg": "#3d3057",
  "caret.stream.fg": "#bd93f9",
};
