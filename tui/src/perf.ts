import type { RunEvent } from "./protocol/events";
import { emptyState, replayEvents } from "./state/reducer";

export function replayForPerf(events: RunEvent[]): { eventCount: number; lastSeq: number; durationMs: number } {
  const started = performance.now();
  const state = replayEvents(emptyState(), events);
  return {
    eventCount: events.length,
    lastSeq: state.activeSession?.lastSeq ?? 0,
    durationMs: performance.now() - started,
  };
}

export function truncateDiff(diff: string, limit = 200_000): { text: string; truncated: boolean } {
  if (diff.length <= limit) return { text: diff, truncated: false };
  return {
    text: `${diff.slice(0, limit)}\n\n[diff truncated at ${limit} characters]`,
    truncated: true,
  };
}
