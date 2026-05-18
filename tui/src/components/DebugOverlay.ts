import type { AppState } from "../state/reducer";

export function renderDebugOverlay(state: AppState): string {
  const session = state.activeSession;
  return [
    "Debug",
    `phase=${state.phase}`,
    `events=${session?.eventsBySeq.size ?? 0}`,
    `lastSeq=${session?.lastSeq ?? 0}`,
    `turns=${session?.turns.length ?? 0}`,
    `replayEvents=${state.replay?.events.length ?? 0}`,
    `replayMs=${state.replay?.replayMs.toFixed(1) ?? "0.0"}`,
  ].join("\n");
}
