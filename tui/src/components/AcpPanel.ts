export function renderAcpPanel(): string {
  return [
    "ACP prototype",
    "",
    "Transport: JSON-RPC over stdio",
    "Command: tinyagent agent stdio --protocol acp",
    "",
    "Method map:",
    "session.start -> create TinyAgent session",
    "session.prompt -> run prompt and emit session.event notifications",
    "session.cancel -> cancellation acknowledgement",
    "approval.resolve -> approval acknowledgement",
    "",
    "stderr is reserved for diagnostics; stdout is JSON-RPC only.",
  ].join("\n");
}
