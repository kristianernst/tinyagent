import { color, semantic } from "../design/tokens";

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
};

const tinyDark: Theme = {
  name: "tiny-dark",
  background: color.bg,
  surface: color.surface,
  surfaceMuted: color.surface2,
  border: color.border,
  borderFocus: color.borderFocus,
  text: color.text,
  textMuted: color.muted,
  textSubtle: color.subtle,
  accent: color.blue,
  success: color.green,
  warning: color.yellow,
  danger: color.red,
  info: color.cyan,
  selectionBg: "#264f78",
  selectionFg: color.text,
  user: color.cyan,
  assistant: color.text,
  reasoning: color.purple,
  tool: color.orange,
  diffAdded: "#0e3a1f",
  diffRemoved: "#3a0e0e",
  diffContext: color.surface,
  spinner: semantic.thinking,
  cursorBg: color.blue,
  cursorFg: color.bg,
};

const tinyLight: Theme = {
  ...tinyDark,
  name: "tiny-light",
  background: "#fafbfc",
  surface: "#ffffff",
  surfaceMuted: "#f0f2f5",
  border: "#d0d7de",
  borderFocus: "#0969da",
  text: "#1f2328",
  textMuted: "#656d76",
  textSubtle: "#8c959f",
  accent: "#0969da",
  selectionBg: "#cce0ff",
  selectionFg: "#1f2328",
  user: "#0a7d52",
  assistant: "#1f2328",
  reasoning: "#8250df",
  tool: "#bc4c00",
  diffAdded: "#dafbe1",
  diffRemoved: "#ffebe9",
  diffContext: "#f6f8fa",
  cursorBg: "#0969da",
  cursorFg: "#ffffff",
};

const dracula: Theme = {
  ...tinyDark,
  name: "dracula",
  background: "#282a36",
  surface: "#21222c",
  surfaceMuted: "#191a21",
  border: "#44475a",
  borderFocus: "#bd93f9",
  text: "#f8f8f2",
  textMuted: "#6272a4",
  textSubtle: "#44475a",
  accent: "#bd93f9",
  success: "#50fa7b",
  warning: "#f1fa8c",
  danger: "#ff5555",
  info: "#8be9fd",
  user: "#8be9fd",
  assistant: "#f8f8f2",
  reasoning: "#bd93f9",
  tool: "#ffb86c",
  selectionBg: "#44475a",
  cursorBg: "#bd93f9",
  cursorFg: "#282a36",
};

const gruvbox: Theme = {
  ...tinyDark,
  name: "gruvbox",
  background: "#282828",
  surface: "#32302f",
  surfaceMuted: "#3c3836",
  border: "#504945",
  borderFocus: "#fabd2f",
  text: "#ebdbb2",
  textMuted: "#a89984",
  textSubtle: "#7c6f64",
  accent: "#fabd2f",
  success: "#b8bb26",
  warning: "#fe8019",
  danger: "#fb4934",
  info: "#83a598",
  user: "#83a598",
  assistant: "#ebdbb2",
  reasoning: "#d3869b",
  tool: "#fe8019",
  selectionBg: "#504945",
  cursorBg: "#fabd2f",
  cursorFg: "#282828",
};

export const themes: Record<string, Theme> = {
  "tiny-dark": tinyDark,
  "tiny-light": tinyLight,
  dracula,
  gruvbox,
};

export function resolveTheme(name: string | undefined): Theme {
  return themes[name ?? ""] ?? tinyDark;
}

export const themeNames = Object.keys(themes);
