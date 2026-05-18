import type { UpdatePanelState } from "../state/reducer";

export function renderUpdatePanel(update: UpdatePanelState): string {
  const result = update.result;
  if (!result) {
    return [
      "Update channel: alpha",
      "Status: not checked",
      "Check: /update check",
      "Apply: /update apply",
      "Rollback: /update rollback",
      update.error ? `Error: ${update.error}` : "",
    ]
      .filter(Boolean)
      .join("\n");
  }
  return [
    `Channel: ${result.channel}`,
    `Current: ${result.current_version}`,
    result.latest_version ? `Latest: ${result.latest_version}` : "",
    `Install: ${result.install_kind}`,
    `Status: ${result.reason}`,
    result.available ? `Ready: ${result.latest_version}` : "",
    result.active_version ? `Active: ${result.active_version}` : "",
    result.previous_version ? `Previous: ${result.previous_version}` : "",
    result.manifest_source ? `Manifest: ${result.manifest_source}` : "",
    update.lastAction ? `Action: ${update.lastAction}` : "",
    update.error ? `Error: ${update.error}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}
