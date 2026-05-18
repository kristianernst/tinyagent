import type { TurnState } from "../state/reducer";

export function renderTranscript(turns: TurnState[]): string {
  if (!turns.length) return "No active run.";
  return turns
    .map((turn) => {
      const reasoning = turn.reasoning.map((block) => `  reasoning: ${block.text}`).join("\n");
      const tools = turn.tools.map((tool) => `  tool ${tool.status}: ${tool.label}${tool.output ? `\n    ${tool.output}` : ""}`).join("\n");
      return [`> ${turn.user}`, reasoning, tools, turn.assistant ? `\n${turn.assistant}` : ""].filter(Boolean).join("\n");
    })
    .join("\n\n");
}
