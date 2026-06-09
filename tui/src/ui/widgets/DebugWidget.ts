import type { AppState } from "../../state/reducer";
import type { Theme } from "../theme";
import { InfoPanelWidget } from "./InfoPanelWidget";

export class DebugWidget {
  readonly node: any;
  private panel: InfoPanelWidget;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.panel = new InfoPanelWidget(opentui, ctx, theme);
    this.node = this.panel.node;
  }

  update(state: AppState): void {
    const session = state.activeSession;
    const stepCount = session?.eventsBySeq.size ?? 0;
    const replaySteps = state.replay?.events.length ?? 0;
    const surface = state.ui.activePanel === "transcript" ? "transcript" : `${state.ui.activePanel} overlay`;
    const surfaceDetail = state.ui.activePanel === "transcript" ? `base surface · diff ${state.ui.diffView}` : `right sheet · diff ${state.ui.diffView}`;
    this.panel.update({
      eyebrow: "debug",
      rows: [
        {
          label: "phase",
          value: state.phase,
          detail: `approval ${state.approvalMode} · ${state.sessionMode} session`,
          tone: state.phase === "failed" ? "danger" : state.phase === "streaming" ? "accent" : "default",
        },
        {
          label: "model",
          value: `${state.provider} · ${state.model}`,
          detail: "next turn",
        },
        {
          label: "theme",
          value: state.ui.theme,
          detail: "semantic layer only · widgets unchanged",
        },
        {
          label: "activity",
          value: `${stepCount} step${stepCount === 1 ? "" : "s"}`,
          detail: `latest step ${session?.lastSeq ?? 0} · ${session?.turns.length ?? 0} turn${session?.turns.length === 1 ? "" : "s"}`,
        },
        {
          label: "replay",
          value: `${replaySteps} step${replaySteps === 1 ? "" : "s"}`,
          detail: `${state.replay?.replayMs.toFixed(1) ?? "0.0"} ms timeline`,
        },
        {
          label: "surface",
          value: surface,
          detail: surfaceDetail,
        },
        {
          label: "reasoning",
          value: state.ui.showReasoning ? "shown" : "folded",
          detail: "transcript fold",
        },
      ],
    });
  }
}
