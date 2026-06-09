import type { UpdatePanelState } from "../../state/reducer";
import type { Theme } from "../theme";
import { InfoPanelWidget } from "./InfoPanelWidget";

export class UpdateWidget {
  readonly node: any;
  private panel: InfoPanelWidget;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.panel = new InfoPanelWidget(opentui, ctx, theme);
    this.node = this.panel.node;
  }

  update(panel: UpdatePanelState): void {
    const result = panel.result;
    if (!result) {
      this.panel.update({
        eyebrow: "update",
        rows: [
          {
            label: "status",
            value: panel.status,
            detail: panel.error || "release source pending",
            tone: panel.error ? "danger" : "muted",
          },
          {
            label: "next",
            value: "check now",
            detail: "refresh release feed",
          },
        ],
        footer: panel.error ? "needs attention · check again" : "check for updates",
      });
      return;
    }
    this.panel.update({
      eyebrow: `${result.channel} channel`,
      rows: [
        {
          label: "version",
          value: result.available ? `${result.current_version} → ${result.latest_version}` : result.current_version,
          detail: result.available ? "new build available" : "current build is up to date",
          tone: result.available ? "warning" : "success",
        },
        {
          label: "install",
          value: result.install_kind,
          detail: result.reason,
        },
        {
          label: "active",
          value: result.active_version || result.current_version,
          detail: result.previous_version ? `previous ${result.previous_version}` : "no rollback target reported",
        },
        {
          label: "source",
          value: releaseSourceValue(result.manifest_source, result.channel),
          detail: releaseSourceDetail(result.manifest_source),
        },
        {
          label: "last",
          value: humanAction(panel.lastAction),
          detail: checkedDetail(result.checked_at),
        },
        ...(panel.error
          ? [
              {
                label: "error",
                value: panel.error,
                detail: "needs attention",
                tone: "danger" as const,
              },
            ]
          : []),
      ],
      footer: updateFooter(panel, result),
    });
  }
}

function releaseSourceValue(source: string, channel: string): string {
  if (!source) return "not reported";
  if (/^https?:\/\//.test(source)) return `${channel} feed`;
  return "local source";
}

function releaseSourceDetail(source: string): string {
  if (!source) return "not reported";
  if (/^https?:\/\//.test(source)) return "checked release service";
  return "local release source";
}

function humanAction(action: string): string {
  if (action === "check") return "checked";
  if (action === "apply") return "applied";
  if (action === "rollback") return "rolled back";
  return action || "none";
}

function checkedDetail(checkedAt: string): string {
  if (!checkedAt) return "no local action";
  return checkedAt.replace("T", " ").replace(/:00(?:\.000)?Z$/, "").replace(/Z$/, "");
}

function updateFooter(panel: UpdatePanelState, result: NonNullable<UpdatePanelState["result"]>): string {
  if (panel.error) return "needs attention · check again";
  if (!result.available) return "checked · no action needed";
  return result.previous_version ? "ready to apply · rollback available" : "ready to apply";
}
