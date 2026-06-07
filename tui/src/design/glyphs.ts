// Layer 1 helper — the whitelist. If a widget needs a glyph not listed here,
// add it here first. See DESIGN_TOKENS.md §2.4.

export const glyphs = {
  // Prefixes
  user: "›",
  system: "·",
  reasoning: "◆",

  // Tool states
  toolRun: "⠋", // placeholder — spinner cycles via spinners.braille
  toolOk: "✓",
  toolFail: "✗",
  toolBlock: "◐",
  toolSkip: "○",

  // Bullets
  bulletDot: "•",
  bulletDiamond: "◆",
  chevron: "›",
  hover: "▸",

  // Carets
  caretIdle: "▏",
  caretStream: "▍",
  enterCue: "↵",

  // Brackets
  pillL: "⦗",
  pillR: "⦘",
  kbdL: "⌜",
  kbdR: "⌟",

  // Tree
  treeBranch: "└",

  // Branch symbol for chrome bar
  branch: "⎇",
  trafficDot: "●",

  // Dividers
  dividerThin: "─",
  dividerDot: "·",
  minus: "−",

  // Box corners
  corner: {
    round: { tl: "╭", tr: "╮", bl: "╰", br: "╯", h: "─", v: "│" },
    heavy: { tl: "┏", tr: "┓", bl: "┗", br: "┛", h: "━", v: "┃" },
    square: { tl: "┌", tr: "┐", bl: "└", br: "┘", h: "─", v: "│" },
  },
} as const;

// Banned glyphs — these used to appear in the codebase and read inconsistently.
// Listed here only as documentation; not exported.
//   ■  ░▒▓█  ASCII logos  -\|/ spinner
