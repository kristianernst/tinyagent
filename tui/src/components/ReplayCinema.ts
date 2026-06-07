import type { ReplayState } from "../state/reducer";
import type { RunEvent } from "../protocol/events";
import { glyphs } from "../design/glyphs";

export function renderReplayCinema(replay: ReplayState | null): string {
  if (!replay || !replay.events.length) return emptyReplay();
  const cursor = replay.cursorSeq || replay.events[replay.events.length - 1]?.seq || 0;
  const window = replay.events.filter((event) => Math.abs(event.seq - cursor) <= 4);
  const rows = window.map((event) => `${event.seq === cursor ? glyphs.caretIdle : " "} ${eventLabel(event).padEnd(28)} ${stepMeta(event.seq)}\n  ${eventDetail(event)}`);
  const projected = replay.projected
    ? [
        "turn preview",
        replayRow(
          "phase",
          replay.projected.phase,
          `${unit(replay.projected.turns, "turn")} · ${unit(replay.projected.tools, "tool")} · ${replay.replayMs.toFixed(1)}ms replay`,
        ),
        replayRow("assistant", "response preview", replay.projected.assistantPreview || "none"),
      ].join("\n")
    : "turn preview\n  no replay state";
  return [
    "replay",
    replayRow("run", humanRunId(replay.runId), "saved trace"),
    replayRow("timeline", `${replay.events.length} steps`, `cursor ${cursor} · replay ${replay.replayMs.toFixed(1)}ms`),
    replay.forkDir ? replayRow("fork", forkSummary(replay.forkDir), forkDetail(replay.forkDir)) : "",
    "",
    rows.join("\n"),
    "",
    projected,
    "",
    selectedEventDetail(replay.rawEvent),
  ]
    .filter(Boolean)
    .join("\n");
}

function emptyReplay(): string {
  return ["replay", replayRow("status", "empty", "no run loaded")].join("\n");
}

function replayRow(label: string, value: string, detail: string): string {
  return [`  ${glyphs.caretIdle} ${label.padEnd(15)}${truncate(value, 31)}`, `    ${truncate(detail, 58)}`].join("\n");
}

function selectedEventDetail(event: RunEvent | null): string {
  if (!event) return "selected step\n  no step selected";
  const rows = [`selected step`, replayRow("step", String(event.seq), eventDetail(event))];
  for (const [key, value] of Object.entries(event.data ?? {}).slice(0, 4)) {
    rows.push(`  ${glyphs.caretIdle} ${key.padEnd(15)}${truncate(formatPayloadValue(value), 58)}`);
  }
  return rows.join("\n");
}

function formatPayloadValue(value: unknown): string {
  if (value === null || value === undefined) return "none";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(formatPayloadValue).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key}: ${formatPayloadValue(item)}`)
      .join(" · ");
  }
  return String(value);
}

function humanRunId(value: string): string {
  return value.replace(/^run[_-]/, "").replace(/[_-]+/g, " ").trim().replace(/\s+/g, " ");
}

function forkSummary(value: string): string {
  if (/^(?:\/private)?\/tmp\//.test(value)) return "workspace copy";
  if (value.includes("/")) return "workspace copy";
  return "fork workspace";
}

function forkDetail(value: string): string {
  if (/^(?:\/private)?\/tmp\//.test(value)) return "temporary workspace";
  if (value.includes("/")) return "workspace copy";
  return "fork workspace";
}

function stepMeta(seq: number): string {
  return `step ${seq}`;
}

function eventLabel(event: RunEvent): string {
  const map: Record<string, string> = {
    "run.started": "run started",
    "run.completed": "run completed",
    "run.failed": "run failed",
    "run.cancelled": "run cancelled",
    "model.reasoning.delta": "reasoning",
    "model.reasoning.completed": "reasoning done",
    "model.text.delta": "assistant delta",
    "model.text.completed": "assistant done",
    "tool.execution.started": "tool started",
    "tool.execution.completed": "tool completed",
    "tool.execution.failed": "tool failed",
    "approval.requested": "approval requested",
    "approval.resolved": "approval resolved",
    "artifact.diff": "diff artifact",
  };
  return map[event.type] ?? event.type.replace(/[._-]+/g, " ");
}

function eventDetail(event: RunEvent): string {
  const tool = payloadText(event.data?.tool);
  const map: Record<string, string> = {
    "run.started": "trace opened",
    "run.completed": "trace complete",
    "run.failed": "turn stopped",
    "run.cancelled": "turn cancelled",
    "model.reasoning.delta": "reasoning stream",
    "model.reasoning.completed": "reasoning sealed",
    "model.text.delta": "assistant text",
    "model.text.completed": "assistant done",
    "tool.execution.started": tool ? `${tool} · running` : "tool running",
    "tool.execution.completed": tool ? `${tool} · output captured` : "tool finished",
    "tool.execution.failed": tool ? `${tool} · failed` : "tool failed",
    "approval.requested": "waiting on approval",
    "approval.resolved": "approval resolved",
    "artifact.diff": "patch artifact",
  };
  return map[event.type] ?? "event payload";
}

function payloadText(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function unit(count: number, label: string): string {
  return `${count} ${label}${count === 1 ? "" : "s"}`;
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, Math.max(0, max - 1))}…`;
}
