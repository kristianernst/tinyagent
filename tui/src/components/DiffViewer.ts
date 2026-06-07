import { truncateDiff } from "../perf";
import type { DiffState } from "../state/reducer";

export function renderDiffViewer(diff: DiffState | null): string {
  if (!diff) return emptyDiff();
  if (!diff.text) {
    return diff.omittedFiles
      ? [
          "diff",
          row("status", "private only", omittedDetail(diff.omittedFiles)),
          row("display", "empty", "no text diff available"),
        ].join("\n")
      : emptyDiff();
  }
  const bounded = truncateDiff(diff.text);
  return [
    "diff",
    diff.paths.length ? row("files", diff.paths.join(", "), unit(diff.paths.length, "changed file")) : "",
    bounded.text,
    bounded.truncated || diff.truncated ? row("status", "truncated", "open diff panel for full patch") : "",
    diff.omittedFiles ? row("omitted", String(diff.omittedFiles), omittedDetail(diff.omittedFiles)) : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function emptyDiff(): string {
  return ["diff", row("status", "empty", "no changes")].join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}

function omittedDetail(count: number): string {
  return `${unit(count, "private file")} omitted`;
}

function unit(count: number, label: string): string {
  return `${count} ${label}${count === 1 ? "" : "s"}`;
}
