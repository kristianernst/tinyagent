import type { UsageStats } from "../state/reducer";

export function renderUsagePanel(usage: UsageStats): string {
  return [
    `Model calls: ${usage.modelCalls}`,
    `Input tokens: ${usage.inputTokens}`,
    `Output tokens: ${usage.outputTokens}`,
    `Total tokens: ${usage.totalTokens}`,
    `Latency ms: ${usage.latencyMs}`,
  ].join("\n");
}
