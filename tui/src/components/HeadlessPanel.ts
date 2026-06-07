import type { AppState } from "../state/reducer";

export function renderHeadlessPanel(state: AppState): string {
  const seq = state.replay?.cursorSeq || state.activeSession?.lastSeq || 1;
  const usage = state.activeSession?.usage;
  const run = `tinyagent run "<prompt>"`;
  return [
    "headless",
    "",
    row("run", "start task", run),
    row("stream", "watch progress", `tinyagent run "<prompt>" --stream text`),
    row("replay", "review run", "tinyagent replay <run-id>"),
    row("fork", `from step ${seq}`, `tinyagent fork <run-path> --at ${seq}`),
    row("eval", "run suite", "tinyagent eval <suite-path>"),
    row("draft skill", "capture pattern", "tinyagent skills draft-from-run <run-path>"),
    row("usage", usage ? `${usage.totalTokens} tok · ${usage.modelCalls} ${usage.modelCalls === 1 ? "call" : "calls"}` : "after first run", "saved with run summary"),
    row("bridge", "connect clients", "tinyagent agent stdio --protocol tinyagent"),
    "same trace · cli parity",
  ]
    .filter(Boolean)
    .join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}
