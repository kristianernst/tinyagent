import { commands } from "../commands";

export function renderCommandPalette(query = ""): string {
  const needle = query.toLowerCase();
  return commands
    .filter((command) => !needle || command.id.includes(needle) || command.title.toLowerCase().includes(needle))
    .map((command) => `/${command.id.padEnd(16)} ${command.title}`)
    .join("\n");
}
