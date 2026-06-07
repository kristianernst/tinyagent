import type { TurnState } from "../state/reducer";
import { glyphs } from "../design/glyphs";
import { toolLaneName } from "../ui/toolLabels";

export function renderTranscript(turns: TurnState[]): string {
  if (!turns.length) return ["transcript", row("status", "idle", "no active run")].join("\n");
  return turns
    .map((turn) => {
      const reasoning = turn.reasoning
        .map((block) => [`  ${glyphs.reasoning} thought${block.completed ? "" : "…"}`, indent(block.text)].join("\n"))
        .join("\n");
      const tools = turn.tools
        .map((tool) => [`  ${toolGlyph(tool.status)} ${toolLaneName(tool, 8)}${tool.label}`, `    ${tool.status}${tool.output ? ` · ${tool.output}` : ""}`].join("\n"))
        .join("\n");
      return [`${glyphs.user} ${turn.user}`, reasoning, tools, turn.assistant ? `\n${turn.assistant}` : ""].filter(Boolean).join("\n");
    })
    .join("\n\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}

function indent(value: string): string {
  return value
    .split("\n")
    .map((line) => `    ${line}`)
    .join("\n");
}

function toolGlyph(status: TurnState["tools"][number]["status"]): string {
  if (status === "done") return glyphs.toolOk;
  if (status === "failed") return glyphs.toolFail;
  if (status === "blocked") return glyphs.toolBlock;
  if (status === "cancelled") return glyphs.toolSkip;
  return glyphs.toolRun;
}
