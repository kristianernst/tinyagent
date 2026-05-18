import type { UsageStats } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export class UsageWidget {
  readonly node: any;
  private summary: any;
  private bars: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.summary = makeText(opentui, ctx, { content: "", fg: theme.accent });
    this.bars = makeText(opentui, ctx, { content: "", fg: theme.text, marginTop: 1 });
    this.node.add?.(this.summary);
    this.node.add?.(this.bars);
  }

  update(usage: UsageStats): void {
    if (this.summary && this.summary.content !== undefined) {
      this.summary.content = [
        `Model calls: ${usage.modelCalls}`,
        `Latency: ${usage.latencyMs} ms`,
        `Total tokens: ${usage.totalTokens}`,
      ].join("  ·  ");
    }
    const denom = Math.max(1, usage.inputTokens + usage.outputTokens);
    const inputBar = bar(usage.inputTokens, denom, 30);
    const outputBar = bar(usage.outputTokens, denom, 30);
    if (this.bars && this.bars.content !== undefined) {
      this.bars.content = [
        `Input  ${String(usage.inputTokens).padStart(6)}  ${inputBar}`,
        `Output ${String(usage.outputTokens).padStart(6)}  ${outputBar}`,
      ].join("\n");
    }
  }
}

function bar(value: number, total: number, width: number): string {
  const filled = Math.max(0, Math.min(width, Math.round((value / total) * width)));
  return `${"█".repeat(filled)}${"░".repeat(width - filled)}`;
}
