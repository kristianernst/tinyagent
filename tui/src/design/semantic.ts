// Layer 2: intent. Widgets read these names.
// Themes override values; the names never change.

import { chroma } from "./primitives";

export type SemanticTokens = {
  // Surfaces
  "surface.canvas": string;
  "surface.raised": string;
  "surface.sunken": string;
  "surface.overlay": string;
  "surface.modal": string;

  // Borders
  "border.subtle": string;
  "border.strong": string;
  "border.focus": string;
  "border.danger": string;

  // Text
  "text.primary": string;
  "text.secondary": string;
  "text.tertiary": string;
  "text.disabled": string;
  "text.on-accent": string;
  "text.on-danger": string;

  // Accent
  "accent.fg": string;
  "accent.soft": string;

  // Status (fg + soft fill)
  "status.success.fg": string;
  "status.success.soft": string;
  "status.warning.fg": string;
  "status.warning.soft": string;
  "status.danger.fg": string;
  "status.danger.soft": string;
  "status.info.fg": string;
  "status.info.soft": string;

  // Roles
  "role.user.fg": string;
  "role.assistant.fg": string;
  "role.reasoning.fg": string;
  "role.tool.idle.fg": string;
  "role.tool.ok.fg": string;
  "role.tool.fail.fg": string;
  "role.system.fg": string;

  // Diff
  "diff.added.bg": string;
  "diff.added.fg": string;
  "diff.removed.bg": string;
  "diff.removed.fg": string;
  "diff.context.bg": string;
  "diff.gutter.fg": string;

  // Selection + caret
  "selection.bg": string;
  "selection.fg": string;
  "clickable.row.hover.bg": string;
  "clickable.row.press.bg": string;
  "clickable.glyph.hover.fg": string;
  "caret.idle.fg": string;
  "caret.stream.fg": string;
};

export type ChromaKey = keyof typeof chroma;
