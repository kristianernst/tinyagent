import type { SemanticTokens } from "../semantic";

// Accessibility theme: AAA-oriented contrast, one accent, no palette drift.
export const highContrast: SemanticTokens = {
  "surface.canvas": "#000000",
  "surface.raised": "#050505",
  "surface.sunken": "#000000",
  "surface.overlay": "#0a0a0a",
  "surface.modal": "#050505",

  "border.subtle": "#8f8f8f",
  "border.strong": "#ffffff",
  "border.focus": "#00e5ff",
  "border.danger": "#ffffff",

  "text.primary": "#ffffff",
  "text.secondary": "#f2f2f2",
  "text.tertiary": "#d6d6d6",
  "text.disabled": "#8f8f8f",
  "text.on-accent": "#000000",
  "text.on-danger": "#000000",

  "accent.fg": "#00e5ff",
  "accent.soft": "#00333a",

  "status.success.fg": "#ffffff",
  "status.success.soft": "#1c1c1c",
  "status.warning.fg": "#ffffff",
  "status.warning.soft": "#1c1c1c",
  "status.danger.fg": "#ffffff",
  "status.danger.soft": "#1c1c1c",
  "status.info.fg": "#00e5ff",
  "status.info.soft": "#00333a",

  "role.user.fg": "#00e5ff",
  "role.assistant.fg": "#ffffff",
  "role.reasoning.fg": "#f2f2f2",
  "role.tool.idle.fg": "#d6d6d6",
  "role.tool.ok.fg": "#ffffff",
  "role.tool.fail.fg": "#ffffff",
  "role.system.fg": "#d6d6d6",

  "diff.added.bg": "#1c1c1c",
  "diff.added.fg": "#ffffff",
  "diff.removed.bg": "#1c1c1c",
  "diff.removed.fg": "#ffffff",
  "diff.context.bg": "#000000",
  "diff.gutter.fg": "#d6d6d6",

  "selection.bg": "#00e5ff",
  "selection.fg": "#000000",
  "clickable.row.hover.bg": "#1c1c1c",
  "clickable.row.press.bg": "#00333a",
  "clickable.glyph.hover.fg": "#00e5ff",
  "caret.idle.fg": "#00333a",
  "caret.stream.fg": "#00e5ff",
};
