import type { ReplayState } from "../state/reducer";

export function renderReplayCinema(replay: ReplayState | null): string {
  if (!replay || !replay.events.length) return "No replay loaded.";
  const cursor = replay.cursorSeq || replay.events[replay.events.length - 1]?.seq || 0;
  const window = replay.events.filter((event) => Math.abs(event.seq - cursor) <= 4);
  const rows = window.map((event) => `${event.seq === cursor ? ">" : " "} ${String(event.seq).padStart(4, "0")} ${event.type}`);
  const raw = replay.rawEvent ? JSON.stringify(replay.rawEvent.data ?? {}, null, 2).slice(0, 1200) : "{}";
  const projected = replay.projected
    ? [
        `Projected: ${replay.projected.phase}`,
        `Turns: ${replay.projected.turns}`,
        `Tools: ${replay.projected.tools}`,
        `Assistant: ${replay.projected.assistantPreview || "none"}`,
      ].join("\n")
    : "Projected: none";
  return [
    `Run: ${replay.runId}`,
    `Events: ${replay.events.length}`,
    `Cursor: ${cursor}`,
    `Replay: ${replay.replayMs.toFixed(1)} ms`,
    replay.forkDir ? `Fork: ${replay.forkDir}` : "",
    "",
    rows.join("\n"),
    "",
    projected,
    "",
    `Raw event data:\n${raw}`,
  ]
    .filter(Boolean)
    .join("\n");
}
