export function frame(title: string, body: string, width = 80): string {
  const inner = Math.max(20, width - 2);
  const header = ` ${title} `;
  const top = `┌${header}${"─".repeat(Math.max(0, inner - header.length))}┐`;
  const bottom = `└${"─".repeat(inner)}┘`;
  const lines = body.split("\n").map((line) => `│${line.slice(0, inner).padEnd(inner, " ")}│`);
  return [top, ...lines, bottom].join("\n");
}
