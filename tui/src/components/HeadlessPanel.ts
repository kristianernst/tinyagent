import type { AppState } from "../state/reducer";

export function renderHeadlessPanel(state: AppState): string {
  const runId = state.activeSession?.runId ?? "<run-id>";
  const runPath = state.activeSession?.runPath || "<run_path>";
  const seq = state.replay?.cursorSeq || state.activeSession?.lastSeq || 1;
  const task = state.activeSession?.turns.at(-1)?.user || "<task>";
  const usage = state.activeSession?.usage;
  return [
    "Headless equivalents",
    "",
    `Run JSON: tinyagent run ${quote(task)} --output-format json`,
    `Stream JSONL: tinyagent run ${quote(task)} --stream jsonl --debug 1`,
    `Replay: tinyagent replay ${runId}`,
    `Fork: tinyagent fork ${runPath} --at ${seq}`,
    "Eval: tinyagent eval <suite-path>",
    `Draft skill: tinyagent skills draft-from-run ${runPath}`,
    `Usage JSON: tinyagent run ${quote(task)} --output-format json | jq .usage`,
    usage ? `Current usage: ${usage.totalTokens} tokens across ${usage.modelCalls} call${usage.modelCalls === 1 ? "" : "s"}` : "",
    "Stdio: tinyagent agent stdio --protocol tinyagent",
  ]
    .filter(Boolean)
    .join("\n");
}

function quote(value: string): string {
  return JSON.stringify(value);
}
