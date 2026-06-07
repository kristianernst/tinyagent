import type { UsageStats } from "../state/reducer";

export function renderUsagePanel(usage: UsageStats): string {
  const denom = Math.max(1, usage.inputTokens + usage.outputTokens);
  return [
    "usage",
    row("total tokens", formatNumber(usage.totalTokens), `${formatNumber(usage.inputTokens)} in · ${formatNumber(usage.outputTokens)} out`),
    row("model calls", formatNumber(usage.modelCalls), averageTokens(usage)),
    row("latency", formatLatencyValue(usage.latencyMs), formatLatencyDetail(usage.latencyMs)),
    row("input", formatNumber(usage.inputTokens), bar(usage.inputTokens, denom, 30)),
    row("output", formatNumber(usage.outputTokens), bar(usage.outputTokens, denom, 30)),
  ].join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}

function bar(value: number, total: number, width: number): string {
  const filled = Math.max(0, Math.min(width, Math.round((value / total) * width)));
  return `${"▰".repeat(filled)}${"▱".repeat(width - filled)}`;
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatLatencyValue(ms: number): string {
  if (!ms) return "no sample";
  if (ms < 1000) return `${formatNumber(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatLatencyDetail(ms: number): string {
  return ms ? "end to end" : "waiting for model call";
}

function averageTokens(usage: UsageStats): string {
  if (!usage.modelCalls) return "no calls yet";
  return `${formatNumber(Math.round(usage.totalTokens / usage.modelCalls))} tok/call avg`;
}
