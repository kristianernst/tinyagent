import type { FailureExplanation } from "../state/reducer";

export function renderFailurePanel(failure: FailureExplanation | null): string {
  if (!failure) return ["failure review", row("status", "clear", "no failed step in this run")].join("\n");
  return [
    "failure review",
    row("source", failure.source, "stopped turn"),
    row("last ok", stepValue(failure.lastSuccessfulEvent), `${eventKind(failure.lastSuccessfulEvent)} · safe checkpoint`),
    row("failed", stepValue(failure.failedEvent), `${eventKind(failure.failedEvent)} · replay target`),
    "recovery actions",
    ...failure.recoveryActions.map((action) => actionRow(action)),
  ].join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}

function actionRow(action: string): string {
  const rewind = action.match(/\/rewind\s+(\d+)/);
  if (action.includes("/replay")) return row("inspect", "/replay", "open replay");
  if (rewind) return row("rewind", `/rewind ${rewind[1]}`, `step ${rewind[1]}`);
  if (/retry/i.test(action)) return row("retry", "compact prompt", "smaller bundle");
  return row("action", action, "copy hint");
}

function stepValue(value: string): string {
  const seq = value.trim().match(/^(\d+)/)?.[1];
  return seq ? `step ${seq}` : value;
}

function eventKind(value: string): string {
  const type = value.trim().replace(/^\d+\s+/, "");
  if (type === "tool.execution.completed") return "tool completed";
  if (type === "model.call.failed") return "model failed";
  if (type === "model.call.started") return "model started";
  return type.replace(/\./g, " ");
}
