import type { AppState } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export class DebugWidget {
  readonly node: any;
  private body: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.body = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.node.add?.(this.body);
  }

  update(state: AppState): void {
    const session = state.activeSession;
    const lines = [
      `phase: ${state.phase}`,
      `provider: ${state.provider} · model: ${state.model}`,
      `events: ${session?.eventsBySeq.size ?? 0}`,
      `lastSeq: ${session?.lastSeq ?? 0}`,
      `turns: ${session?.turns.length ?? 0}`,
      `replayEvents: ${state.replay?.events.length ?? 0}`,
      `replayMs: ${state.replay?.replayMs.toFixed(1) ?? "0.0"}`,
      `approvalMode: ${state.approvalMode} · sessionMode: ${state.sessionMode}`,
      `theme: ${state.ui.theme} · panel: ${state.ui.activePanel}`,
      `rail: ${state.ui.rightRail ? "visible" : "hidden"} · palette: ${state.ui.paletteOpen ? "open" : "closed"}`,
      `showReasoning: ${state.ui.showReasoning} · diffView: ${state.ui.diffView}`,
    ];
    if (this.body && this.body.content !== undefined) this.body.content = lines.join("\n");
  }
}
