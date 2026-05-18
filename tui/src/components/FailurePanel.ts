import type { FailureExplanation } from "../state/reducer";

export function renderFailurePanel(failure: FailureExplanation | null): string {
  if (!failure) return "No failure detected in the loaded run.";
  return [
    `Source: ${failure.source}`,
    `Last successful event: ${failure.lastSuccessfulEvent}`,
    `Failed event: ${failure.failedEvent}`,
    "",
    "Recovery actions:",
    ...failure.recoveryActions.map((action) => `- ${action}`),
  ].join("\n");
}
