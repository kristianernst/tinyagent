import type { SemanticTokens } from "../semantic";

// Mono drops chroma. Used for recordings, demos, CI snapshots. The only color
// is the terminal's foreground; we still tier text by lightness via the
// neutral ramp.
export const mono: SemanticTokens = {
  "surface.canvas": "#0d1117",
  "surface.raised": "#131822",
  "surface.sunken": "#0a0e14",
  "surface.overlay": "#1a2030",
  "surface.modal": "#131822",

  "border.subtle": "#1f2733",
  "border.strong": "#2a3340",
  "border.focus": "#ffffff",
  "border.danger": "#ffffff",

  "text.primary": "#e8eef5",
  "text.secondary": "#9aa4b1",
  "text.tertiary": "#6a7480",
  "text.disabled": "#4a5260",
  "text.on-accent": "#0a0e14",
  "text.on-danger": "#0a0e14",

  "accent.fg": "#ffffff",
  "accent.soft": "#2a3340",

  "status.success.fg": "#e8eef5",
  "status.success.soft": "#1f2733",
  "status.warning.fg": "#e8eef5",
  "status.warning.soft": "#1f2733",
  "status.danger.fg": "#e8eef5",
  "status.danger.soft": "#1f2733",
  "status.info.fg": "#9aa4b1",
  "status.info.soft": "#1f2733",

  "role.user.fg": "#e8eef5",
  "role.assistant.fg": "#e8eef5",
  "role.reasoning.fg": "#9aa4b1",
  "role.tool.idle.fg": "#9aa4b1",
  "role.tool.ok.fg": "#e8eef5",
  "role.tool.fail.fg": "#e8eef5",
  "role.system.fg": "#6a7480",

  "diff.added.bg": "#1f2733",
  "diff.added.fg": "#e8eef5",
  "diff.removed.bg": "#1f2733",
  "diff.removed.fg": "#e8eef5",
  "diff.context.bg": "#0a0e14",
  "diff.gutter.fg": "#6a7480",

  "selection.bg": "#2a3340",
  "selection.fg": "#e8eef5",
  "clickable.row.hover.bg": "#1f2733",
  "clickable.row.press.bg": "#2a3340",
  "clickable.glyph.hover.fg": "#ffffff",
  "caret.idle.fg": "#2a3340",
  "caret.stream.fg": "#ffffff",
};
