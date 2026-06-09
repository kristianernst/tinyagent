import type { TinyAgentClient } from "../backend/client";
import type { RunEvent } from "../protocol/events";
import {
  emptyState,
  replayEvents,
  type AppPhase,
  type FailureExplanation,
  type ReplayState,
} from "../state/reducer";
import type { Store } from "../state/store";
import { appendError } from "./errors";
import type { ActiveRun } from "./runs";

const failureEventTypes = new Set([
  "run.failed",
  "turn.failed",
  "step.failed",
  "step.timeout",
  "step.idle_timeout",
  "finish.blocked",
  "model.call.failed",
  "model.timeout",
  "model.idle_timeout",
  "model.cancelled",
  "model.tool_call.assembly.failed",
  "tool.execution.failed",
  "tool.execution.blocked",
]);

export async function loadReplay(client: TinyAgentClient, store: Store, runId: string): Promise<void> {
  if (!runId) {
    appendError(store, "Replay needs a run id.");
    return;
  }
  const workspaceId = store.get().activeWorkspaceId ?? undefined;
  const events = await client.events(runId, workspaceId);
  const replay = buildReplayState(runId, events, events[events.length - 1]?.seq ?? 0);
  const state = store.get();
  store.set({ ...state, replay, failure: explainFailure(events) });
}

export async function rewindReplay(client: TinyAgentClient, store: Store, seqArg: string | undefined, activeRun: ActiveRun | null): Promise<void> {
  const state = store.get();
  const runId = state.replay?.runId ?? activeRun?.runId ?? state.activeSession?.runId ?? "";
  if (!state.replay && runId) await loadReplay(client, store, runId);
  const replay = store.get().replay;
  if (!replay) return;
  const fallback = replay.events[replay.events.length - 1]?.seq ?? 0;
  const cursor = Number.parseInt(seqArg ?? String(fallback), 10);
  store.set({
    ...store.get(),
    replay: buildReplayState(replay.runId, replay.events, Number.isFinite(cursor) ? cursor : fallback, replay.forkDir),
  });
}

export async function forkReplay(client: TinyAgentClient, store: Store, args: string[], activeRun: ActiveRun | null): Promise<void> {
  const state = store.get();
  const replay = state.replay;
  const runId = args[1] ?? replay?.runId ?? activeRun?.runId ?? state.activeSession?.runId ?? "";
  const at = args[0] ?? String(replay?.cursorSeq || state.activeSession?.lastSeq || 0);
  if (!runId || !at || at === "0") {
    appendError(store, "Fork needs a run id and event seq.");
    return;
  }
  const fork = await client.forkRun(runId, at, state.activeWorkspaceId ?? undefined);
  const events = replay?.runId === runId && replay.events.length
    ? replay.events
    : await client.events(runId, state.activeWorkspaceId ?? undefined);
  const cursor = Number.parseInt(at, 10);
  store.set({
    ...store.get(),
    replay: buildReplayState(runId, events, Number.isFinite(cursor) ? cursor : events[events.length - 1]?.seq ?? 0, fork.fork_dir),
    failure: explainFailure(events),
  });
}

export function buildReplayState(runId: string, events: RunEvent[], cursorSeq: number, forkDir = ""): ReplayState {
  const started = performance.now();
  const cursor = Math.max(0, cursorSeq);
  const visible = events.filter((event) => event.seq <= cursor || cursor === 0);
  const projected = replayProjection(visible);
  const rawEvent = events.find((event) => event.seq === cursor) ?? events[events.length - 1] ?? null;
  return {
    runId,
    events,
    cursorSeq: rawEvent?.seq ?? cursor,
    rawEvent,
    projected,
    forkDir,
    replayMs: performance.now() - started,
  };
}

function replayProjection(events: RunEvent[]) {
  const projected = replayEvents(emptyState(), events);
  const turn = projected.activeSession?.turns.at(-1);
  return {
    phase: projected.phase as AppPhase,
    lastSeq: projected.activeSession?.lastSeq ?? 0,
    turns: projected.activeSession?.turns.length ?? 0,
    tools: turn?.tools.length ?? 0,
    assistantPreview: (turn?.assistant ?? "").slice(0, 160),
  };
}

export function explainFailure(events: RunEvent[]): FailureExplanation | null {
  const failed = events.find((event) => failureEventTypes.has(event.type));
  if (!failed) return null;
  const lastSuccessful = [...events].reverse().find((event) => event.seq < failed.seq && !failureEventTypes.has(event.type));
  const source = failed.type.startsWith("tool.") ? "tool" : failed.type.startsWith("model.") ? "model" : "run";
  return {
    source,
    lastSuccessfulEvent: lastSuccessful ? `${lastSuccessful.seq} ${lastSuccessful.type}` : "none",
    failedEvent: `${failed.seq} ${failed.type}`,
    recoveryActions: [
      "Inspect raw failed event with /replay.",
      "Project state before failure with /rewind <seq>.",
      "Fork from the last good event with /fork <seq>.",
    ],
  };
}
