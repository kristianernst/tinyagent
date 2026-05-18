export const spinners: Record<string, string[]> = {
  ascii: ["-", "\\", "|", "/"],
  dots: [".   ", "..  ", "... ", "...."],
  braille: ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
  scanline: ["░", "▒", "▓", "█", "▓", "▒", "░"],
  minimal: ["·", "·", "·"],
};

export function spinnerFrame(name: string, tick: number): string {
  const frames = spinners[name] ?? spinners.ascii;
  return frames[tick % frames.length].padEnd(Math.max(...frames.map((frame) => frame.length)), " ");
}
