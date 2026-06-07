import type { EvalLabState } from "../state/reducer";

export function renderEvalLab(evalLab: EvalLabState): string {
  const rows = evalLab.results.slice(0, 12).map((result) => {
    const outcome = result.success ? "pass" : "fail";
    return row(result.case_id, outcome, result.failure_reason || result.status);
  });
  return [
    "eval",
    row("status", evalLab.status, statusDetail(evalLab)),
    evalLab.suitePath ? row("suite", evalLab.suitePath, "snapshot gate") : "",
    evalLab.outputDir ? row("output", "latest run", evalLab.outputDir) : "",
    evalLab.error ? row("error", evalLab.error, "needs attention") : "",
    rows.length ? "cases" : "",
    ...rows,
    summary(evalLab),
  ]
    .filter(Boolean)
    .join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}

function statusDetail(evalLab: EvalLabState): string {
  if (evalLab.error) return evalLab.error;
  if (evalLab.status === "completed") {
    const passed = evalLab.results.filter((result) => result.success).length;
    return `${passed} / ${evalLab.results.length} passing`;
  }
  if (evalLab.status === "running") return "suite running";
  return "waiting for suite";
}

function summary(evalLab: EvalLabState): string {
  if (evalLab.error) return row("review", "needs attention", evalLab.error);
  if (evalLab.status !== "completed") return "";
  const failed = evalLab.results.filter((result) => !result.success);
  if (!failed.length) return row("review", "clear", "all cases passing");
  const first = failed[0]!;
  return row("review", "needs review", `${first.case_id}${first.failure_reason ? ` · ${first.failure_reason}` : ""}`);
}
