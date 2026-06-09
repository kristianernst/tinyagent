// Layer 1 of the design system: raw values only.
// Widgets MUST NOT import from this file. Themes override semantic tokens; the
// semantic layer reads primitives. See DESIGN_TOKENS.md §1 for the contract.

export const neutralDark = {
  50: "#f3f6fa",
  100: "#e6edf3",
  200: "#c9d1d9",
  300: "#8b949e",
  400: "#6e7681",
  500: "#4a5260",
  600: "#2a3340",
  700: "#1f2733",
  800: "#1a2030",
  850: "#131822",
  900: "#0d1117",
  950: "#0a0e14",
} as const;

export const neutralLight = {
  50: "#fafbfc",
  100: "#f3f5f8",
  200: "#eaecef",
  300: "#a8b1bd",
  400: "#6e7681",
  500: "#4a5260",
  600: "#353a44",
  700: "#d0d7de",
  800: "#eaecef",
  850: "#f3f5f8",
  900: "#161c23",
  950: "#ffffff",
} as const;

export const chroma = {
  brand: "#5b9dff",
  success: "#4ac26b",
  warning: "#d9a341",
  danger: "#ef5350",
  info: "#56d6a4",
  reason: "#b48aff",
} as const;

// Spacing — terminal cells. space.5 intentionally omitted.
export const space = {
  0: 0,
  1: 1,
  2: 2,
  3: 3,
  4: 4,
  6: 6,
} as const;

// Frame-based motion. 30 fps event loop → 33 ms/frame.
export const FRAME_MS = 33;

export const motion = {
  fast: 2, // ≈ 66 ms — selection move, focus ring
  beat: 4, // ≈ 132 ms — spinner step
  slow: 8, // ≈ 266 ms — caret blink
  dwell: 16, // ≈ 533 ms — toast lifetime min
  streamGate: 1, // ≤ 1 frame — streaming flush rate
} as const;

export const motionMs = {
  fast: 66,
  beat: 132,
  slow: 266,
  dwell: 533,
  streamGate: FRAME_MS,
} as const;
