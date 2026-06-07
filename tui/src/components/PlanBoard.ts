import type { AppState } from "../state/reducer";

export function renderPlanBoard(state: AppState): string {
  return ["session mode", state.sessionMode === "plan" ? row("mode", "plan", "write tools locked") : row("mode", "build", "write tools available")].join(
    "\n",
  );
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}
