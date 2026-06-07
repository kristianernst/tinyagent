export function renderModelLab(provider: string, model = ""): string {
  return [
    "model state",
    row("provider", provider, "next turn"),
    row("model", model || "default", "generation model"),
  ].join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}
