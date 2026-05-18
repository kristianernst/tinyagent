import type { ReplayState } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeSelect, makeText } from "../layout";

export class ReplayWidget {
  readonly node: any;
  private header: any;
  private select: any;
  private raw: any;
  private projection: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.header = makeText(opentui, ctx, { content: "No replay loaded.", fg: theme.textMuted });
    this.select = makeSelect(opentui, ctx, {
      options: [],
      showDescription: false,
      backgroundColor: theme.surface,
      textColor: theme.text,
      selectedBackgroundColor: theme.selectionBg,
      selectedTextColor: theme.selectionFg,
      showScrollIndicator: true,
      wrapSelection: true,
      focusable: true,
      minHeight: 4,
      flexGrow: 1,
    });
    this.projection = makeText(opentui, ctx, { content: "", fg: theme.assistant, marginTop: 1 });
    this.raw = makeText(opentui, ctx, { content: "", fg: theme.textSubtle, marginTop: 1 });
    this.node.add?.(this.header);
    this.node.add?.(this.select);
    this.node.add?.(this.projection);
    this.node.add?.(this.raw);
  }

  update(replay: ReplayState | null): void {
    if (!replay || !replay.events.length) {
      if (this.header && this.header.content !== undefined) this.header.content = "No replay loaded.";
      if (this.select && "options" in this.select) this.select.options = [];
      if (this.projection && this.projection.content !== undefined) this.projection.content = "";
      if (this.raw && this.raw.content !== undefined) this.raw.content = "";
      return;
    }
    const cursor = replay.cursorSeq || replay.events[replay.events.length - 1]?.seq || 0;
    if (this.header && this.header.content !== undefined) {
      this.header.content = `Run: ${replay.runId} · events: ${replay.events.length} · cursor: ${cursor} · replay: ${replay.replayMs.toFixed(1)}ms${replay.forkDir ? ` · fork: ${replay.forkDir}` : ""}`;
    }
    if (this.select && "options" in this.select) {
      this.select.options = replay.events.map((event) => ({
        name: `${event.seq === cursor ? ">" : " "} ${String(event.seq).padStart(4, "0")} ${event.type}`,
        description: event.type,
        value: String(event.seq),
      }));
    }
    if (this.projection && this.projection.content !== undefined) {
      const p = replay.projected;
      this.projection.content = p
        ? `phase=${p.phase} · turns=${p.turns} · tools=${p.tools}\nassistant: ${p.assistantPreview || "(none)"}`
        : "no projection";
    }
    if (this.raw && this.raw.content !== undefined) {
      const raw = replay.rawEvent ? JSON.stringify(replay.rawEvent.data ?? {}, null, 2) : "{}";
      this.raw.content = raw.length > 1200 ? `${raw.slice(0, 1200)}…` : raw;
    }
  }
}
