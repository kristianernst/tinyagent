import type { UpdatePanelState } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export class UpdateWidget {
  readonly node: any;
  private summary: any;
  private detail: any;
  private hint: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.summary = makeText(opentui, ctx, { content: "", fg: theme.accent });
    this.detail = makeText(opentui, ctx, { content: "", fg: theme.text, marginTop: 1 });
    this.hint = makeText(opentui, ctx, {
      content: "/update check · /update apply · /update rollback",
      fg: theme.textSubtle,
      marginTop: 1,
    });
    this.node.add?.(this.summary);
    this.node.add?.(this.detail);
    this.node.add?.(this.hint);
  }

  update(panel: UpdatePanelState): void {
    const result = panel.result;
    const summary = result
      ? `${result.channel} · ${result.current_version}${result.available ? ` → ${result.latest_version}` : " (up to date)"}`
      : "channel alpha · status: not checked";
    if (this.summary && this.summary.content !== undefined) this.summary.content = summary;
    const lines = result
      ? [
          `Install: ${result.install_kind}`,
          `Status: ${result.reason}`,
          result.active_version ? `Active: ${result.active_version}` : "",
          result.previous_version ? `Previous: ${result.previous_version}` : "",
          result.manifest_source ? `Manifest: ${result.manifest_source}` : "",
          panel.lastAction ? `Last action: ${panel.lastAction}` : "",
          panel.error ? `Error: ${panel.error}` : "",
        ]
      : [panel.error ? `Error: ${panel.error}` : "Use /update check to query the manifest."];
    if (this.detail && this.detail.content !== undefined) this.detail.content = lines.filter(Boolean).join("\n");
  }
}
