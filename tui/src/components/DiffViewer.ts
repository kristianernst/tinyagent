import { truncateDiff } from "../perf";
import type { DiffState } from "../state/reducer";

export function renderDiffViewer(diff: DiffState | null): string {
  if (!diff) return "No diff.";
  if (!diff.text) {
    return diff.omittedFiles ? `${diff.omittedFiles} private file${diff.omittedFiles === 1 ? "" : "s"} omitted.` : "No diff.";
  }
  const bounded = truncateDiff(diff.text);
  const paths = diff.paths.length ? `Files: ${diff.paths.join(", ")}\n` : "";
  const omitted = diff.omittedFiles ? `\n[${diff.omittedFiles} private file${diff.omittedFiles === 1 ? "" : "s"} omitted]` : "";
  return `${paths}${bounded.text}${bounded.truncated || diff.truncated ? "\n[truncated]" : ""}${omitted}`;
}
