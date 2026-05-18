import type { AppState } from "../state/reducer";

export function renderPlanBoard(state: AppState): string {
  return state.sessionMode === "plan"
    ? "Plan mode active. Write tools are blocked by backend policy."
    : "Plan mode inactive.";
}
