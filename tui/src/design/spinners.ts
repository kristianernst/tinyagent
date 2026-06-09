// Braille-only spinner set. Per DESIGN_TOKENS.md §6.1 the only animated glyph
// in the system is the 10-frame braille. `spinnerFrame(name, tick)` keeps the
// old signature for back-compat; the `name` argument is now ignored. We log on
// non-braille names once per session so any straggler config gets caught.

import { motion } from "./primitives";

const BRAILLE = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export const spinners: Record<string, string[]> = {
  braille: BRAILLE,
};

const warned = new Set<string>();

function warnForRemovedSpinner(name: string): void {
  if (name && name !== "braille" && !warned.has(name)) {
    warned.add(name);
    if (process.env.DEBUG) {
      console.warn(`[tinyagent] spinner "${name}" removed; using braille.`);
    }
  }
}

function frameAt(tick: number, cadenceFrames: number): string {
  const cadence = Math.max(1, Math.floor(cadenceFrames));
  const step = cadence === 1 ? tick : tick === 0 ? 0 : Math.ceil(tick / cadence);
  return BRAILLE[((step % BRAILLE.length) + BRAILLE.length) % BRAILLE.length] ?? BRAILLE[0]!;
}

export function spinnerFrame(name: string, tick: number): string {
  warnForRemovedSpinner(name);
  return frameAt(tick, 1);
}

export function spinnerBeatFrame(name: string, tick: number): string {
  warnForRemovedSpinner(name);
  return frameAt(tick, motion.beat);
}
