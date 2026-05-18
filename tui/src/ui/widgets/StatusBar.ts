import { spinnerFrame } from "../../design/spinners";
import type { AppState } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export class StatusBarWidget {
  readonly node: any;
  private spinnerNode: any;
  private statusNode: any;
  private metaNode: any;
  private tick = 0;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      height: 1,
      flexDirection: "row",
      paddingX: 1,
      backgroundColor: theme.surface,
    });
    this.spinnerNode = makeText(opentui, ctx, { content: " ", fg: theme.spinner });
    this.statusNode = makeText(opentui, ctx, { content: "", fg: theme.textMuted, flexGrow: 1, marginX: 1 });
    this.metaNode = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.node.add(this.spinnerNode);
    this.node.add(this.statusNode);
    this.node.add(this.metaNode);
  }

  update(state: AppState): void {
    this.tick = (this.tick + 1) % 1000;
    const phase = state.phase;
    const spinning = phase === "thinking" || phase === "streaming";
    if (this.spinnerNode && this.spinnerNode.content !== undefined) {
      this.spinnerNode.content = spinning ? spinnerFrame(state.ui.spinner, this.tick) : phaseGlyph(phase);
    }
    if (this.statusNode && this.statusNode.content !== undefined) {
      this.statusNode.content = renderStatus(state);
    }
    if (this.metaNode && this.metaNode.content !== undefined) {
      this.metaNode.content = renderMeta(state);
    }
  }
}

function phaseGlyph(phase: string): string {
  if (phase === "approval") return "?";
  if (phase === "failed") return "!";
  return "*";
}

function renderStatus(state: AppState): string {
  const workspace = state.workspaces.find((item) => item.workspace_id === state.activeWorkspaceId)?.name ?? "no-workspace";
  const mode = state.sessionMode === "plan" ? "plan" : state.approvalMode;
  return `${state.phase} · ${workspace} · ${mode} · ${state.activeSession?.runId ?? "no-run"}`;
}

function renderMeta(state: AppState): string {
  const usage = state.activeSession?.usage;
  const tokens = usage ? `${usage.totalTokens} tok` : "0 tok";
  const calls = usage ? `${usage.modelCalls} call${usage.modelCalls === 1 ? "" : "s"}` : "0 calls";
  const update = state.updatePanel.result?.available ? `update ${state.updatePanel.result.latest_version}` : "";
  return [tokens, calls, `${state.provider}/${state.model}`, update].filter(Boolean).join(" · ");
}
