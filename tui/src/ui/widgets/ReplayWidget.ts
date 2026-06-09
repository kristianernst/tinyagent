import type { ReplayState } from "../../state/reducer";
import type { RunEvent } from "../../protocol/events";
import { glyphs } from "../../design/glyphs";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";
import { makePanelList } from "./panelStyle";

export class ReplayWidget {
  readonly node: any;
  private header: any;
  private select: any;
  private eventDetail: any;
  private projection: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.header = makeText(opentui, ctx, { content: emptyReplayHeader(), fg: theme.textMuted });
    this.select = makePanelList(opentui, ctx, theme, {
      showDescription: true,
      minHeight: 4,
      height: 10,
      flexShrink: 0,
      maxRows: 5,
      maxTextWidth: 52,
    });
    this.projection = makeText(opentui, ctx, { content: "", fg: theme.assistant, marginTop: 1 });
    this.eventDetail = makeText(opentui, ctx, { content: "", fg: theme.textSubtle, marginTop: 1 });
    this.node.add?.(this.header);
    this.node.add?.(this.select);
    this.node.add?.(this.projection);
    this.node.add?.(this.eventDetail);
  }

  update(replay: ReplayState | null): void {
    if (!replay || !replay.events.length) {
      if (this.header && this.header.content !== undefined) this.header.content = emptyReplayHeader();
      if (this.select && "options" in this.select) this.select.options = [];
      if (this.projection && this.projection.content !== undefined) this.projection.content = "";
      if (this.eventDetail && this.eventDetail.content !== undefined) this.eventDetail.content = "";
      return;
    }
    const cursor = replay.cursorSeq || replay.events[replay.events.length - 1]?.seq || 0;
    if (this.header && this.header.content !== undefined) {
      this.header.content = [
        "replay",
        replayRow("run", humanRunId(replay.runId), "saved trace"),
        replayRow("timeline", `${replay.events.length} steps`, `cursor ${cursor} · replay ${replay.replayMs.toFixed(1)}ms`),
        replay.forkDir ? replayRow("fork", forkSummary(replay.forkDir), forkDetail(replay.forkDir)) : "",
      ]
        .filter(Boolean)
        .join("\n");
    }
    if (this.select && "options" in this.select) {
      this.select.options = replay.events.map((event) => ({
        name: eventLabel(event),
        description: eventDetail(event),
        rightMeta: stepMeta(event.seq),
        value: String(event.seq),
      }));
      const cursorIndex = replay.events.findIndex((event) => event.seq === cursor);
      if (cursorIndex >= 0 && "selectedIndex" in this.select) this.select.selectedIndex = cursorIndex;
    }
    if (this.projection && this.projection.content !== undefined) {
      const p = replay.projected;
      this.projection.content = p
        ? [
            "turn preview",
            replayRow("phase", p.phase, `${unit(p.turns, "turn")} · ${unit(p.tools, "tool")} · ${replay.replayMs.toFixed(1)}ms replay`),
            replayRow("assistant", "response preview", p.assistantPreview || "none"),
          ].join("\n")
        : "turn preview\n  no replay state";
    }
    if (this.eventDetail && this.eventDetail.content !== undefined) {
      this.eventDetail.content = selectedEventDetail(replay.rawEvent);
    }
  }
}

function emptyReplayHeader(): string {
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
  return value
    .replace(/^run[_-]/, "")
    .replace(/[_-]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
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
