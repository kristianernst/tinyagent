import type { UpdatePanelState } from "../state/reducer";

export function renderUpdatePanel(update: UpdatePanelState): string {
  const result = update.result;
  if (!result) {
    return [
      "update",
      row("channel", "alpha", "default release lane"),
      row("status", "not checked", "release source pending"),
      row("next", "check now", "refresh release feed"),
      update.error ? row("error", update.error, "needs attention") : "",
    ]
      .filter(Boolean)
      .join("\n");
  }
  return [
    "update",
    row("channel", result.channel, "release lane"),
    row("current", result.current_version, "installed version"),
    result.latest_version ? row("latest", result.latest_version, result.available ? "ready" : "reported") : "",
    row("install", result.install_kind, result.platform || "local platform"),
    row("status", result.reason, result.available ? "update available" : "up to date"),
    result.active_version ? row("active", result.active_version, "active build") : "",
    result.previous_version ? row("previous", result.previous_version, "rollback target") : "",
    result.manifest_source ? row("source", releaseSourceValue(result.manifest_source, result.channel), releaseSourceDetail(result.manifest_source)) : "",
    update.lastAction ? row("last", humanAction(update.lastAction), result.checked_at || "local action") : "",
    update.error ? row("error", update.error, "needs attention") : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}

function humanAction(action: string): string {
  if (action === "check") return "checked";
  if (action === "apply") return "applied";
  if (action === "rollback") return "rolled back";
  return action || "none";
}

function releaseSourceValue(source: string, channel: string): string {
  if (/^https?:\/\//.test(source)) return `${channel} feed`;
  return "local source";
}

function releaseSourceDetail(source: string): string {
  if (/^https?:\/\//.test(source)) return "checked release service";
  return "local release source";
}
