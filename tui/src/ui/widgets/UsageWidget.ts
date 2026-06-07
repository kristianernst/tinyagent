import type { UsageStats } from "../../state/reducer";
import type { Theme } from "../theme";
import { InfoPanelWidget } from "./InfoPanelWidget";

export class UsageWidget {
  readonly node: any;
  private panel: InfoPanelWidget;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.panel = new InfoPanelWidget(opentui, ctx, theme);
    this.node = this.panel.node;
  }

  update(usage: UsageStats): void {
    const denom = Math.max(1, usage.inputTokens + usage.outputTokens);
    this.panel.update({
      eyebrow: "usage",
      rows: [
        {
          label: "total tokens",
          value: formatNumber(usage.totalTokens),
          detail: `${formatNumber(usage.inputTokens)} in · ${formatNumber(usage.outputTokens)} out`,
          tone: "accent",
        },
        {
          label: "model calls",
          value: formatNumber(usage.modelCalls),
          detail: averageTokens(usage),
        },
        {
          label: "latency",
          value: formatLatencyValue(usage.latencyMs),
          detail: formatLatencyDetail(usage.latencyMs),
        },
        {
          label: "input",
          value: formatNumber(usage.inputTokens),
          detail: bar(usage.inputTokens, denom, 30),
          tone: "success",
        },
        {
          label: "output",
          value: formatNumber(usage.outputTokens),
          detail: bar(usage.outputTokens, denom, 30),
          tone: "warning",
        },
      ],
    });
  }
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
