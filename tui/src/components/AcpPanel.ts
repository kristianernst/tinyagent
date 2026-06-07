export function renderAcpPanel(): string {
  return [
    "acp bridge",
    row("bridge", "live session", "app-connected turn stream"),
    row("command", "app bridge", "tinyagent agent stdio --protocol acp"),
    "methods",
    row("start", "open session", "create conversation"),
    row("prompt", "stream turn", "send user prompt"),
    row("cancel", "stop run", "return control"),
    row("approval", "resolve tool", "allow or deny"),
    "same trace · app parity",
  ].join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}
