import type { AppState, ToolCallView, TurnState } from "./reducer";

export function activeTurn(state: AppState): TurnState | null {
  const turns = state.activeSession?.turns ?? [];
  return turns[turns.length - 1] ?? null;
}

export function runningTools(state: AppState): ToolCallView[] {
  return activeTurn(state)?.tools.filter((tool) => tool.status === "running") ?? [];
}

export function currentStatusLine(state: AppState): string {
  const workspace = state.workspaces.find((item) => item.workspace_id === state.activeWorkspaceId);
  const mode = state.sessionMode === "plan" ? "plan" : state.approvalMode;
  const run = state.activeSession?.runId ?? "no-run";
  return `${state.phase} | ${workspace?.name ?? "no-workspace"} | ${mode} | ${run}`;
}
