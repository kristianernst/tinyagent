import type { AppState } from "../state/reducer";

export function renderDebugOverlay(state: AppState): string {
  const session = state.activeSession;
  const stepCount = session?.eventsBySeq.size ?? 0;
  const replaySteps = state.replay?.events.length ?? 0;
  const surface = state.ui.activePanel === "transcript" ? "transcript" : `${state.ui.activePanel} overlay`;
  const surfaceDetail = state.ui.activePanel === "transcript" ? `base surface · diff ${state.ui.diffView}` : `right sheet · diff ${state.ui.diffView}`;
  return [
    "debug",
    row("phase", state.phase, `approval ${state.approvalMode} · ${state.sessionMode} session`),
    row("model", `${state.provider} · ${state.model}`, "next turn"),
    row("theme", state.ui.theme, "semantic layer only · widgets unchanged"),
    row("activity", `${stepCount} step${stepCount === 1 ? "" : "s"}`, `latest step ${session?.lastSeq ?? 0} · ${session?.turns.length ?? 0} turn${session?.turns.length === 1 ? "" : "s"}`),
    row("replay", `${replaySteps} step${replaySteps === 1 ? "" : "s"}`, `${state.replay?.replayMs.toFixed(1) ?? "0.0"} ms timeline`),
    row("surface", surface, surfaceDetail),
    row("reasoning", state.ui.showReasoning ? "shown" : "folded", "transcript fold"),
  ].join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}
