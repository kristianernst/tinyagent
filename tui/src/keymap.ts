export type KeyAction =
  | "send"
  | "close"
  | "interrupt"
  | "palette"
  | "rightRail"
  | "plan"
  | "diff"
  | "usage"
  | "nextFocus"
  | "previousFocus"
  | "help";

export const keymap: Record<string, KeyAction> = {
  Enter: "send",
  Escape: "close",
  "Ctrl+C": "interrupt",
  "Ctrl+K": "palette",
  "Ctrl+R": "rightRail",
  "Ctrl+P": "plan",
  "Ctrl+D": "diff",
  "Ctrl+U": "usage",
  Tab: "nextFocus",
  "Shift+Tab": "previousFocus",
  "?": "help",
};
