// Legacy re-export. The token system now lives in primitives.ts + semantic.ts
// + themes/*. New code should import from those files; this stub exists only
// so any straggler `import { color, semantic } from "@/design/tokens"` keeps
// working. Delete when no callers remain.

import { chroma, neutralDark } from "./primitives";

export const color = {
  bg: neutralDark[900],
  surface: neutralDark[850],
  surface2: neutralDark[800],
  border: neutralDark[700],
  borderFocus: chroma.brand,
  text: "#e8eef5",
  muted: "#9aa4b1",
  subtle: "#6a7480",
  blue: chroma.brand,
  cyan: chroma.info,
  green: chroma.success,
  yellow: chroma.warning,
  red: chroma.danger,
  purple: chroma.reason,
} as const;

export const semantic = {
  thinking: chroma.reason,
  planning: chroma.warning,
  reading: chroma.brand,
  searching: chroma.info,
  editing: chroma.brand,
  success: chroma.success,
  danger: chroma.danger,
  approval: chroma.warning,
  muted: color.muted,
} as const;
