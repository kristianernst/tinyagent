import { pickerCommands } from "../commands";
import { glyphs } from "../design/glyphs";

export function renderCommandPalette(query = ""): string {
  const needle = query.toLowerCase();
  const matches = pickerCommands.filter((command) => !needle || command.id.includes(needle) || command.title.toLowerCase().includes(needle));
  if (!matches.length) return `no matches · ${glyphs.kbdL}esc${glyphs.kbdR} cancel`;
  const visible = matches.slice(0, 8);
  return [
    `${glyphs.pillL} / ${glyphs.pillR} commands ${visible.length} / ${matches.length}`,
    ...visible.map((command, index) => `${index === 0 ? glyphs.chevron : " "}/${command.id.padEnd(14)} ${command.title}`),
    `${glyphs.kbdL}↑↓${glyphs.kbdR} move   ${glyphs.kbdL}⏎${glyphs.kbdR} run   ${glyphs.kbdL}esc${glyphs.kbdR} cancel`,
  ].join("\n");
}
