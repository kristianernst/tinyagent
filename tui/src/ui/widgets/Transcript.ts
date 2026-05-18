import type { ReasoningBlock, ToolCallView, TurnState } from "../../state/reducer";
import { plainMarkdown } from "../markdown";
import type { Theme } from "../theme";
import { makeBox, makeMarkdown, makeScrollBox, makeText, syntaxStyleFor } from "../layout";

type TurnNodes = {
  card: any;
  user: any;
  reasoning: any;
  reasoningBox: any;
  tools: any;
  assistant: any;
  status: any;
  lastReasoning: string;
  lastAssistant: string;
};

export class TranscriptWidget {
  readonly node: any;
  private scrollBox: any;
  private contentNode: any;
  private syntaxStyle: any;
  private cards = new Map<string, TurnNodes>();
  private showReasoning = false;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.syntaxStyle = syntaxStyleFor(opentui, theme);
    this.scrollBox = makeScrollBox(opentui, ctx, {
      flexGrow: 1,
      width: "100%",
      minHeight: 4,
      backgroundColor: theme.background,
      stickyScroll: true,
      stickyStart: "bottom",
      scrollY: true,
      viewportCulling: false,
      focusable: true,
      contentOptions: { flexDirection: "column", width: "100%" },
    });
    this.contentNode = this.scrollBox.content ?? this.scrollBox;
    this.node = this.scrollBox;
  }

  setShowReasoning(value: boolean): void {
    this.showReasoning = value;
    for (const card of this.cards.values()) {
      if (card.reasoningBox && "visible" in card.reasoningBox) {
        card.reasoningBox.visible = value && card.lastReasoning.length > 0;
      }
    }
  }

  setTurns(turns: TurnState[]): void {
    const seen = new Set<string>();
    for (const turn of turns) {
      seen.add(turn.id);
      const existing = this.cards.get(turn.id);
      if (existing) {
        this.refreshCard(existing, turn);
      } else {
        const card = this.buildCard(turn);
        this.cards.set(turn.id, card);
        this.contentNode.add?.(card.card);
      }
    }
    for (const [id, card] of this.cards) {
      if (seen.has(id)) continue;
      this.contentNode.remove?.(card.card.id ?? id);
      this.cards.delete(id);
    }
  }

  reset(): void {
    for (const [id, card] of this.cards) {
      this.contentNode.remove?.(card.card.id ?? id);
    }
    this.cards.clear();
  }

  private buildCard(turn: TurnState): TurnNodes {
    const card = makeBox(this.opentui, this.ctx, {
      flexDirection: "column",
      paddingX: 1,
      paddingY: 0,
      marginBottom: 1,
      borderStyle: "single",
      border: ["left"],
      borderColor: this.theme.border,
      width: "100%",
      flexShrink: 0,
    });
    const user = makeText(this.opentui, this.ctx, {
      content: prefixUser(turn.user),
      fg: this.theme.user,
    });
    const reasoning = makeText(this.opentui, this.ctx, {
      content: collapseReasoning(turn.reasoning),
      fg: this.theme.reasoning,
    });
    const reasoningBox = makeBox(this.opentui, this.ctx, {
      flexDirection: "column",
      paddingY: 0,
      visible: this.showReasoning && turn.reasoning.length > 0,
    });
    reasoningBox.add?.(reasoning);

    const tools = makeBox(this.opentui, this.ctx, {
      flexDirection: "column",
      paddingY: 0,
    });
    renderTools(this.opentui, this.ctx, this.theme, tools, turn.tools);

    const assistant = makeMarkdown(this.opentui, this.ctx, {
      content: turn.assistant || "",
      streaming: turn.phase === "streaming",
      syntaxStyle: this.syntaxStyle,
      fg: this.theme.assistant,
      width: "100%",
      flexShrink: 0,
      wrapMode: "word",
    });

    const status = makeText(this.opentui, this.ctx, {
      content: renderTurnStatus(turn),
      fg: this.theme.textMuted,
    });

    card.add?.(user);
    card.add?.(reasoningBox);
    card.add?.(tools);
    card.add?.(assistant);
    card.add?.(status);

    return {
      card,
      user,
      reasoning,
      reasoningBox,
      tools,
      assistant,
      status,
      lastReasoning: collapseReasoning(turn.reasoning),
      lastAssistant: turn.assistant || "",
    };
  }

  private refreshCard(card: TurnNodes, turn: TurnState): void {
    if (card.user && card.user.content !== undefined) card.user.content = prefixUser(turn.user);
    const reasoningText = collapseReasoning(turn.reasoning);
    if (card.reasoning && card.reasoning.content !== undefined && reasoningText !== card.lastReasoning) {
      card.reasoning.content = reasoningText;
      card.lastReasoning = reasoningText;
    }
    if (card.reasoningBox && "visible" in card.reasoningBox) {
      card.reasoningBox.visible = this.showReasoning && reasoningText.length > 0;
    }
    renderTools(this.opentui, this.ctx, this.theme, card.tools, turn.tools);
    const next = turn.assistant || "";
    if (next !== card.lastAssistant) {
      if (card.assistant && card.assistant.content !== undefined) {
        card.assistant.content = next;
      }
      card.lastAssistant = next;
    }
    if (card.assistant && "streaming" in card.assistant) {
      card.assistant.streaming = turn.phase === "streaming" || turn.phase === "thinking";
    }
    if (card.status && card.status.content !== undefined) card.status.content = renderTurnStatus(turn);
  }
}

function prefixUser(text: string): string {
  if (!text) return "› (empty prompt)";
  return text
    .split("\n")
    .map((line, index) => (index === 0 ? `› ${line}` : `  ${line}`))
    .join("\n");
}

function collapseReasoning(blocks: ReasoningBlock[]): string {
  if (!blocks.length) return "";
  return blocks.map((block) => plainMarkdown(block.text, 96)).join("\n\n");
}

function renderTurnStatus(turn: TurnState): string {
  const bits: string[] = [`phase: ${turn.phase}`];
  if (turn.tools.length) bits.push(`${turn.tools.length} tool${turn.tools.length === 1 ? "" : "s"}`);
  if (turn.startedAt) bits.push(`started ${turn.startedAt}`);
  if (turn.completedAt) bits.push(`completed ${turn.completedAt}`);
  return bits.join(" · ");
}

function renderTools(opentui: any, ctx: any, theme: Theme, container: any, tools: ToolCallView[]): void {
  if (!container) return;
  if (container.children?.length && container._toolCount === tools.length) {
    // Update in place
    for (let i = 0; i < tools.length; i++) {
      const node = container.children[i];
      if (node && node.content !== undefined) node.content = renderToolLine(tools[i]);
      if (node && "fg" in node) node.fg = toolColor(theme, tools[i]);
    }
    return;
  }
  // Rebuild
  if (container.children && Array.isArray(container.children)) {
    for (const child of [...container.children]) container.remove?.(child.id ?? child);
  }
  for (const tool of tools) {
    container.add?.(
      makeText(opentui, ctx, {
        content: renderToolLine(tool),
        fg: toolColor(theme, tool),
      }),
    );
  }
  container._toolCount = tools.length;
}

function renderToolLine(tool: ToolCallView): string {
  const icon = toolIcon(tool.status);
  const head = `${icon} ${tool.tool}`;
  const label = tool.argsSummary ? `  ${tool.argsSummary}` : "";
  const output = tool.output ? `\n    ${trimOutput(tool.output)}` : "";
  return `${head}${label ? `\n${label}` : ""}${output}`;
}

function toolIcon(status: string): string {
  if (status === "running") return "•";
  if (status === "done") return "✓";
  if (status === "failed") return "✗";
  if (status === "blocked") return "■";
  if (status === "cancelled") return "○";
  return "·";
}

function toolColor(theme: Theme, tool: ToolCallView): string {
  if (tool.status === "failed") return theme.danger;
  if (tool.status === "blocked") return theme.warning;
  if (tool.status === "cancelled") return theme.textSubtle;
  if (tool.status === "done") return theme.success;
  return theme.tool;
}

function trimOutput(output: string): string {
  const flat = output.replace(/\s+\n/g, "\n");
  const limit = 600;
  if (flat.length <= limit) return flat;
  return `${flat.slice(0, limit)} … (+${flat.length - limit} bytes)`;
}
