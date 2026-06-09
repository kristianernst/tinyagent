import type { AppState, ToolCallView, TurnState } from "./reducer";

export function activeTurn(state: AppState): TurnState | null {
  const turns = state.activeSession?.turns ?? [];
  return turns[turns.length - 1] ?? null;
}

export function runningTools(state: AppState): ToolCallView[] {
  return activeTurn(state)?.tools.filter((tool) => tool.status === "running") ?? [];
}
