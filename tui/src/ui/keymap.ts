export type KeyContext = "global" | "composer" | "transcript" | "palette" | "modal" | "rail";

export type KeyAction =
  | "send"
  | "newline"
  | "interrupt"
  | "stop"
  | "cancel"
  | "close-overlay"
  | "open-palette"
  | "open-help"
  | "toggle-rail"
  | "toggle-plan"
  | "toggle-diff"
  | "toggle-usage"
  | "toggle-debug"
  | "toggle-reasoning"
  | "approve"
  | "deny"
  | "history-prev"
  | "history-next"
  | "history-search"
  | "scroll-up"
  | "scroll-down"
  | "scroll-page-up"
  | "scroll-page-down"
  | "scroll-home"
  | "scroll-end"
  | "next-focus"
  | "previous-focus"
  | "clear-screen"
  | "copy-last"
  | "switch-theme"
  | "quit"
  | "compact-mode"
  | "always-approve"
  | "ask-approve"
  | "plan-mode"
  | "build-mode";

export type KeyBinding = {
  context: KeyContext;
  combo: string;
  action: KeyAction;
};

export const defaultKeymap: KeyBinding[] = [
  // Global
  { context: "global", combo: "Ctrl+K", action: "open-palette" },
  { context: "global", combo: "Ctrl+P", action: "open-palette" },
  { context: "global", combo: "?", action: "open-help" },
  { context: "global", combo: "Ctrl+R", action: "history-search" },
  { context: "global", combo: "Ctrl+B", action: "toggle-rail" },
  { context: "global", combo: "Ctrl+D", action: "toggle-diff" },
  { context: "global", combo: "Ctrl+U", action: "toggle-usage" },
  { context: "global", combo: "Ctrl+L", action: "clear-screen" },
  { context: "global", combo: "Ctrl+O", action: "copy-last" },
  { context: "global", combo: "Alt+t", action: "switch-theme" },
  { context: "global", combo: "Alt+r", action: "toggle-reasoning" },
  { context: "global", combo: "Alt+d", action: "toggle-debug" },
  { context: "global", combo: "Ctrl+C", action: "interrupt" },
  { context: "global", combo: "Tab", action: "next-focus" },
  { context: "global", combo: "Shift+Tab", action: "previous-focus" },

  // Composer
  { context: "composer", combo: "Enter", action: "send" },
  { context: "composer", combo: "Shift+Enter", action: "newline" },
  { context: "composer", combo: "Up", action: "history-prev" },
  { context: "composer", combo: "Down", action: "history-next" },
  { context: "composer", combo: "Ctrl+R", action: "history-search" },

  // Transcript
  { context: "transcript", combo: "PageUp", action: "scroll-page-up" },
  { context: "transcript", combo: "PageDown", action: "scroll-page-down" },
  { context: "transcript", combo: "Home", action: "scroll-home" },
  { context: "transcript", combo: "End", action: "scroll-end" },
  { context: "transcript", combo: "Up", action: "scroll-up" },
  { context: "transcript", combo: "Down", action: "scroll-down" },

  // Palette
  { context: "palette", combo: "Escape", action: "close-overlay" },
  { context: "palette", combo: "Enter", action: "send" },

  // Modal
  { context: "modal", combo: "Escape", action: "close-overlay" },
  { context: "modal", combo: "a", action: "approve" },
  { context: "modal", combo: "A", action: "approve" },
  { context: "modal", combo: "y", action: "approve" },
  { context: "modal", combo: "d", action: "deny" },
  { context: "modal", combo: "D", action: "deny" },
  { context: "modal", combo: "n", action: "deny" },
];

export function comboFromKeyEvent(event: { name?: string; ctrl?: boolean; meta?: boolean; shift?: boolean; sequence?: string }): string {
  const parts: string[] = [];
  if (event.ctrl) parts.push("Ctrl");
  if (event.meta) parts.push("Alt");
  if (event.shift) parts.push("Shift");
  const key = event.name || event.sequence || "";
  if (!key) return "";
  const named = canonicalKey(key);
  parts.push(named);
  return parts.join("+");
}

function canonicalKey(name: string): string {
  switch (name) {
    case "return":
      return "Enter";
    case "escape":
      return "Escape";
    case "backspace":
      return "Backspace";
    case "tab":
      return "Tab";
    case "space":
      return "Space";
    case "up":
      return "Up";
    case "down":
      return "Down";
    case "left":
      return "Left";
    case "right":
      return "Right";
    case "pageup":
      return "PageUp";
    case "pagedown":
      return "PageDown";
    case "home":
      return "Home";
    case "end":
      return "End";
    default:
      return name;
  }
}

export function lookupAction(bindings: KeyBinding[], context: KeyContext, combo: string): KeyAction | null {
  if (!combo) return null;
  const lower = combo.toLowerCase();
  for (const binding of bindings) {
    if (binding.context !== context) continue;
    if (binding.combo.toLowerCase() === lower) return binding.action;
  }
  if (context !== "global") return lookupAction(bindings, "global", combo);
  return null;
}

export function loadKeymap(custom: KeyBinding[] = []): KeyBinding[] {
  if (!custom.length) return defaultKeymap;
  const seen = new Set<string>();
  const merged: KeyBinding[] = [];
  for (const binding of custom) {
    seen.add(`${binding.context}:${binding.combo.toLowerCase()}`);
    merged.push(binding);
  }
  for (const binding of defaultKeymap) {
    if (seen.has(`${binding.context}:${binding.combo.toLowerCase()}`)) continue;
    merged.push(binding);
  }
  return merged;
}
