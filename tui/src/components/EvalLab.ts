import type { EvalLabState } from "../state/reducer";

export function renderEvalLab(evalLab: EvalLabState): string {
  const rows = evalLab.results.slice(0, 12).map((result) => {
    const outcome = result.success ? "pass" : "fail";
    return `${result.case_id.padEnd(24)} ${outcome.padEnd(4)} ${result.status}`;
  });
  return [
    `Status: ${evalLab.status}`,
    evalLab.suitePath ? `Suite: ${evalLab.suitePath}` : "",
    evalLab.outputDir ? `Output: ${evalLab.outputDir}` : "",
    evalLab.command ? `CLI: ${evalLab.command}` : "",
    evalLab.error ? `Error: ${evalLab.error}` : "",
    rows.length ? "\nCase                      Pass Status" : "",
    ...rows,
    evalLab.report ? `\n${evalLab.report.split("\n").slice(0, 12).join("\n")}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}
