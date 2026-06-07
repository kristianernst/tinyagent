import { spinnerBeatFrame } from "../../design/spinners";
import { glyphs } from "../../design/glyphs";
import type { DiffState, ReasoningBlock, ToolCallView, TurnState } from "../../state/reducer";
import { plainMarkdown } from "../markdown";
import type { Theme } from "../theme";
import { makeBox, makeScrollBox, makeText, syntaxStyleFor } from "../layout";
import { toolLaneName } from "../toolLabels";

const PATCH_PREVIEW_LINES = 8;
const DEFAULT_VIEWPORT_WIDTH = 120;
const TRANSCRIPT_CHROME_WIDTH = 8;

// The transcript is the page (DESIGN_TOKENS.md §4.2). No per-turn card border,
// no per-turn status footer. Turns are separated by a `divider.thin` row that
// only appears between turns that *produced output*. Tool calls render inline
// in the transcript and resolve in place (same row mutates from the braille
// spinner to ✓ or ✗ — never appended).

const TOOL_NAME_LANE = 8; // ` read    ` cells reserved before the description

type TurnNodes = {
  outer: any;
  divider: any; // null on the first card; non-null on every card after.
  inner: any;
  user: any;
  reasoning: any;
  reasoningBody: any;
  reasoningBox: any;
  tools: any;
  assistant: any;
  assistantTail: any;
  lastReasoning: string;
  lastAssistant: string;
  lastTurn: TurnState;
};

export class TranscriptWidget {
  readonly node: any;
  private scrollBox: any;
  private contentNode: any;
  private syntaxStyle: any;
  private cards = new Map<string, TurnNodes>();
  private showReasoning = false;
  private tick = 0;
  private order: string[] = [];
  private expandedReasoning = new Set<string>();
  private expandedTools = new Set<string>();
  private hoveredReasoningId: string | null = null;
  private hoveredToolId: string | null = null;
  private patchPreview: any;
  private patchHeader: any;
  private patchBody: any;
  private patchAttached = false;
  private patchAttachedParent: any = null;
  private patchVisible = false;
  private currentDiff: DiffState | null = null;
  private viewportWidth = DEFAULT_VIEWPORT_WIDTH;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.syntaxStyle = syntaxStyleFor(opentui, theme);
    this.scrollBox = makeScrollBox(opentui, ctx, {
      flexGrow: 1,
      width: "100%",
      minHeight: 4,
      backgroundColor: theme.background,
      paddingX: 2,
      paddingY: 1,
      stickyScroll: true,
      stickyStart: "bottom",
      scrollY: true,
      viewportCulling: false,
      focusable: true,
      contentOptions: { flexDirection: "column", width: "100%" },
    });
    // opentui's ScrollBox auto-hides the scrollbar only when content overflows.
    // For the transcript we want the visual quiet of the design system: the
    // scrollbar should be invisible until the user scrolls back through
    // history. Hide it explicitly here; mouse-wheel scrolling still works.
    if (this.scrollBox?.verticalScrollBar) {
      this.scrollBox.verticalScrollBar.visible = false;
    }
    this.contentNode = this.scrollBox.content ?? this.scrollBox;
    this.node = this.scrollBox;

    this.patchPreview = makeBox(opentui, ctx, {
      flexDirection: "column",
      width: "100%",
      borderStyle: "rounded",
      border: true,
      borderColor: theme.borderStrong ?? theme.border,
      paddingX: 1,
      paddingY: 0,
      marginTop: 1,
      backgroundColor: theme.surfaceMuted,
      visible: false,
      enableLayout: false,
      flexShrink: 0,
    });
    this.patchHeader = makeText(opentui, ctx, {
      content: "",
      fg: theme.textMuted,
      flexShrink: 0,
    });
    this.patchBody = makeText(opentui, ctx, {
      content: "",
      fg: theme.text,
      flexShrink: 0,
    });
    this.patchPreview.add?.(this.patchHeader);
    this.patchPreview.add?.(this.patchBody);
  }

  setShowReasoning(value: boolean): void {
    this.showReasoning = value;
    for (const card of this.cards.values()) {
      this.refreshReasoning(card);
    }
  }

  setViewportWidth(width: number): void {
    if (!Number.isFinite(width) || width <= 0 || width === this.viewportWidth) return;
    this.viewportWidth = width;
    this.updatePatchPreviewContent();
    for (const card of this.cards.values()) this.refreshCard(card, card.lastTurn);
  }

  setReasoningExpanded(turnId: string, expanded: boolean): void {
    if (expanded) this.expandedReasoning.add(turnId);
    else this.expandedReasoning.delete(turnId);
    const card = this.cards.get(turnId);
    if (card) this.refreshReasoning(card);
  }

  setToolExpanded(toolId: string, expanded: boolean): void {
    if (expanded) this.expandedTools.add(toolId);
    else this.expandedTools.delete(toolId);
    const card = this.cardForTool(toolId);
    if (card) this.refreshCard(card, card.lastTurn);
  }

  setHoveredTool(toolId: string | null): void {
    this.hoveredToolId = toolId;
    for (const card of this.cards.values()) this.refreshCard(card, card.lastTurn);
  }

  setTurns(turns: TurnState[]): void {
    this.tick = (this.tick + 1) % 1_000_000;
    const seen = new Set<string>();
    for (let i = 0; i < turns.length; i++) {
      const turn = turns[i]!;
      seen.add(turn.id);
      const existing = this.cards.get(turn.id);
      if (existing) {
        this.refreshCard(existing, turn);
      } else {
        const card = this.buildCard(turn, i > 0);
        this.cards.set(turn.id, card);
        this.order.push(turn.id);
        this.contentNode.add?.(card.outer);
      }
    }
    for (const [id, card] of this.cards) {
      if (seen.has(id)) continue;
      this.contentNode.remove?.(card.outer.id ?? id);
      this.cards.delete(id);
      this.order = this.order.filter((x) => x !== id);
    }
    if (this.patchVisible) {
      const target = this.targetPatchCard();
      if (target) this.refreshCard(target, target.lastTurn);
    }
    this.refreshPatchPlacement();
  }

  setDiff(diff: DiffState | null): void {
    this.currentDiff = diff;
    const preview = this.updatePatchPreviewContent();
    const visible = Boolean(preview);
    this.patchVisible = visible;
    if (this.patchPreview && "visible" in this.patchPreview) this.patchPreview.visible = visible;
    if (this.patchPreview && "enableLayout" in this.patchPreview) this.patchPreview.enableLayout = visible;
    if (!preview) {
      this.detachPatchPreview();
      for (const card of this.cards.values()) this.refreshCard(card, card.lastTurn);
      return;
    }
    for (const card of this.cards.values()) this.refreshCard(card, card.lastTurn);
    this.refreshPatchPlacement();
  }

  reset(): void {
    this.detachPatchPreview();
    for (const [id, card] of this.cards) {
      this.contentNode.remove?.(card.outer.id ?? id);
    }
    this.cards.clear();
    this.order = [];
    if (this.patchPreview && "visible" in this.patchPreview) this.patchPreview.visible = false;
    if (this.patchPreview && "enableLayout" in this.patchPreview) this.patchPreview.enableLayout = false;
    this.patchVisible = false;
    this.currentDiff = null;
  }

  private buildCard(turn: TurnState, withDivider: boolean): TurnNodes {
    // Outer wraps the optional divider + the inner turn column. The divider
    // never lives inside `inner` so we can hide it cheaply.
    const outer = makeBox(this.opentui, this.ctx, {
      flexDirection: "column",
      width: "100%",
      flexShrink: 0,
    });

    let divider: any = null;
    if (withDivider) {
      divider = makeText(this.opentui, this.ctx, {
        content: glyphs.dividerThin.repeat(64),
        fg: this.theme.border,
        marginY: 1,
      });
      outer.add?.(divider);
    }

    const inner = makeBox(this.opentui, this.ctx, {
      flexDirection: "column",
      width: "100%",
      flexShrink: 0,
    });

    const user = makeText(this.opentui, this.ctx, {
      content: prefixUser(turn, this.lineWidth()),
      fg: this.theme.user,
    });

    const reasoningText = collapseReasoning(turn.reasoning, this.reasoningWidth());
    const reasoningHeader = makeText(this.opentui, this.ctx, {
      content: this.reasoningHeaderContent(turn, reasoningText),
      fg: this.theme.reasoning,
      cursor: "pointer",
    });
    const reasoningBody = makeText(this.opentui, this.ctx, {
      content: reasoningText,
      fg: this.theme.reasoning,
      marginLeft: 2,
    });
    reasoningHeader.onMouseOver = () => {
      this.hoveredReasoningId = turn.id;
      this.refreshReasoningForTurn(turn.id);
    };
    reasoningHeader.onMouseOut = () => {
      if (this.hoveredReasoningId === turn.id) this.hoveredReasoningId = null;
      this.refreshReasoningForTurn(turn.id);
    };
    reasoningHeader.onMouseDown = (event: any) => {
      if (!isPrimaryDown(event)) return;
      this.setReasoningExpanded(turn.id, !this.reasoningExpanded(turn.id));
    };
    const reasoningBox = makeBox(this.opentui, this.ctx, {
      flexDirection: "column",
      marginTop: 1,
      visible: reasoningText.length > 0,
      enableLayout: reasoningText.length > 0,
    });
    reasoningBox.add?.(reasoningHeader);
    reasoningBox.add?.(reasoningBody);
    if (reasoningBody && "visible" in reasoningBody) reasoningBody.visible = this.reasoningExpanded(turn);
    if (reasoningBody && "enableLayout" in reasoningBody) reasoningBody.enableLayout = this.reasoningExpanded(turn);

    const tools = makeBox(this.opentui, this.ctx, {
      flexDirection: "column",
      marginTop: 1,
      height: toolContainerHeight(turn.tools, this.expandedTools),
      flexShrink: 0,
    });
    renderTools(this.opentui, this.ctx, this.theme, tools, turn.tools, this.tick, this.toolRenderState(), this.lineWidth());

    // Assistant body. We use plain Text + soft-wrap rather than MarkdownRenderable
    // for now — Markdown's tree-sitter dependency makes the rendered output
    // brittle in headless captures and the design system is layout-first.
    // A future revision swaps this for makeMarkdown once the markdown render
    // path is verified visually.
    const assistantParts = this.assistantParts(turn);
    const assistant = makeText(this.opentui, this.ctx, {
      content: assistantParts.lead,
      fg: this.theme.assistant,
      flexShrink: 0,
      marginTop: 1,
    });
    const assistantTail = makeText(this.opentui, this.ctx, {
      content: assistantParts.tail,
      fg: this.theme.assistant,
      flexShrink: 0,
      marginTop: 1,
      visible: assistantParts.tail.length > 0,
      enableLayout: assistantParts.tail.length > 0,
    });

    inner.add?.(user);
    inner.add?.(reasoningBox);
    inner.add?.(tools);
    inner.add?.(assistant);
    inner.add?.(assistantTail);

    outer.add?.(inner);

    return {
      outer,
      divider,
      inner,
      user,
      reasoning: reasoningHeader,
      reasoningBody,
      reasoningBox,
      tools,
      assistant,
      assistantTail,
      lastReasoning: reasoningText,
      lastAssistant: turn.assistant || "",
      lastTurn: turn,
    };
  }

  private refreshCard(card: TurnNodes, turn: TurnState): void {
    card.lastTurn = turn;
    if (card.user && card.user.content !== undefined) card.user.content = prefixUser(turn, this.lineWidth());

    const reasoningText = collapseReasoning(turn.reasoning, this.reasoningWidth());
    if (card.reasoningBody && reasoningText !== card.lastReasoning) {
      if ("content" in card.reasoningBody) card.reasoningBody.content = reasoningText;
      card.lastReasoning = reasoningText;
    }
    this.refreshReasoning(card);

    if (card.tools && "height" in card.tools) card.tools.height = toolContainerHeight(turn.tools, this.expandedTools);
    renderTools(this.opentui, this.ctx, this.theme, card.tools, turn.tools, this.tick, this.toolRenderState(), this.lineWidth());

    const next = turn.assistant || "";
    const assistantParts = this.assistantParts(turn);
    if (card.assistant && card.assistant.content !== assistantParts.lead) {
      card.assistant.content = assistantParts.lead;
    }
    if (card.assistantTail) {
      if (card.assistantTail.content !== assistantParts.tail) card.assistantTail.content = assistantParts.tail;
      const tailVisible = assistantParts.tail.length > 0;
      if ("visible" in card.assistantTail) card.assistantTail.visible = tailVisible;
      if ("enableLayout" in card.assistantTail) card.assistantTail.enableLayout = tailVisible;
    }
    card.lastAssistant = next;
  }

  private refreshReasoningForTurn(turnId: string): void {
    const card = this.cards.get(turnId);
    if (card) this.refreshReasoning(card);
  }

  private refreshReasoning(card: TurnNodes): void {
    const visible = card.lastReasoning.length > 0;
    const expanded = this.reasoningExpanded(card.lastTurn.id);
    if (card.reasoningBox && "visible" in card.reasoningBox) card.reasoningBox.visible = visible;
    if (card.reasoningBox && "enableLayout" in card.reasoningBox) card.reasoningBox.enableLayout = visible;
    if (card.reasoning && "content" in card.reasoning) {
      card.reasoning.content = this.reasoningHeaderContent(card.lastTurn, card.lastReasoning);
    }
    if (card.reasoningBody && "visible" in card.reasoningBody) card.reasoningBody.visible = expanded;
    if (card.reasoningBody && "enableLayout" in card.reasoningBody) card.reasoningBody.enableLayout = expanded;
  }

  private reasoningExpanded(input: string | TurnState): boolean {
    const turn = typeof input === "string" ? this.cards.get(input)?.lastTurn : input;
    const turnId = typeof input === "string" ? input : input.id;
    return this.showReasoning || this.expandedReasoning.has(turnId) || turn?.phase === "thinking" || turn?.phase === "streaming";
  }

  private reasoningHeaderContent(turn: TurnState, reasoningText: string): string {
    const hovered = this.hoveredReasoningId === turn.id;
    const marker = hovered ? `${glyphs.hover} ${glyphs.bulletDiamond}` : glyphs.bulletDiamond;
    if (!reasoningText) return `${marker} thinking`;
    return `${marker} ${reasoningSummary(turn.reasoning)}  ${glyphs.kbdL}r${glyphs.kbdR} ${this.reasoningExpanded(turn) ? "collapse" : "expand"}`;
  }

  private toolRenderState(): ToolRenderState {
    return {
      expanded: this.expandedTools,
      hoveredId: this.hoveredToolId,
      onHover: (id) => {
        this.hoveredToolId = id;
        for (const card of this.cards.values()) this.refreshCard(card, card.lastTurn);
      },
      onToggle: (id) => {
        if (this.expandedTools.has(id)) this.expandedTools.delete(id);
        else this.expandedTools.add(id);
        const card = this.cardForTool(id);
        if (card) this.refreshCard(card, card.lastTurn);
      },
    };
  }

  private cardForTool(toolId: string): TurnNodes | null {
    for (const card of this.cards.values()) {
      if (card.lastTurn.tools.some((tool) => tool.id === toolId)) return card;
    }
    return null;
  }

  private refreshPatchPlacement(): void {
    if (!this.patchPreview) return;
    if (!this.patchVisible) {
      this.detachPatchPreview();
      return;
    }
    const card = this.targetPatchCard();
    if (!card) {
      this.attachPatchPreviewTo(this.contentNode);
      return;
    }
    removeRenderable(card.inner, card.assistantTail);
    this.attachPatchPreviewTo(card.inner);
    card.inner.add?.(card.assistantTail);
  }

  private updatePatchPreviewContent(): InlineDiffPreview | null {
    const preview = diffPreview(this.currentDiff, this.patchHeaderWidth());
    if (this.patchHeader && "content" in this.patchHeader) this.patchHeader.content = preview?.header ?? "";
    if (this.patchBody && "content" in this.patchBody) this.patchBody.content = preview?.body ?? "";
    return preview;
  }

  private attachPatchPreviewTo(parent: any): void {
    if (this.patchAttachedParent === parent) return;
    this.detachPatchPreview();
    parent?.add?.(this.patchPreview);
    this.patchAttached = true;
    this.patchAttachedParent = parent;
  }

  private detachPatchPreview(): void {
    if (!this.patchAttachedParent || !this.patchPreview) {
      this.patchAttached = false;
      this.patchAttachedParent = null;
      return;
    }
    removeRenderable(this.patchAttachedParent, this.patchPreview);
    this.patchAttached = false;
    this.patchAttachedParent = null;
  }

  private targetPatchCard(): TurnNodes | null {
    const turnId = this.order[this.order.length - 1];
    return turnId ? this.cards.get(turnId) ?? null : null;
  }

  private assistantParts(turn: TurnState): { lead: string; tail: string } {
    return splitAssistantAroundPatch(turn.assistant || "", this.assistantWidth(), this.patchVisible && this.targetPatchCard()?.lastTurn.id === turn.id);
  }

  private lineWidth(): number {
    return Math.max(48, this.viewportWidth - TRANSCRIPT_CHROME_WIDTH);
  }

  private assistantWidth(): number {
    return Math.max(40, this.lineWidth() - 2);
  }

  private reasoningWidth(): number {
    return Math.max(40, this.lineWidth() - 16);
  }

  private patchHeaderWidth(): number {
    return Math.max(40, this.lineWidth() - 4);
  }
}

function prefixUser(turn: TurnState, width: number): string {
  const text = turn.user;
  const meta = turnMeta(turn);
  if (!text) return `${glyphs.user} (empty prompt)`;
  return text
    .split("\n")
    .map((line, index) => (index === 0 ? withRightMeta(`${glyphs.user} ${line}`, meta, width) : `  ${line}`))
    .join("\n");
}

function turnMeta(turn: TurnState): string {
  const time = formatTime(turn.startedAt);
  if (!time) return "";
  if (turn.phase === "thinking" || turn.phase === "streaming" || turn.phase === "approval") return `${time} · just now`;
  return time;
}

function formatTime(value: string | undefined): string {
  if (!value) return "";
  if (/^\d{1,2}:\d{2}$/.test(value)) return value;
  const parsed = parseTimestamp(value);
  if (parsed == null) return "";
  const date = new Date(parsed);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function parseTimestamp(value: string | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return null;
  return parsed;
}

function collapseReasoning(blocks: ReasoningBlock[], width: number): string {
  if (!blocks.length) return "";
  return blocks.map((block) => plainMarkdown(block.text, width)).join("\n\n");
}

function reasoningSummary(blocks: ReasoningBlock[]): string {
  if (!blocks.length) return "thinking";
  if (blocks.every((b) => b.completed)) {
    const duration = reasoningDurationMs(blocks);
    if (duration != null) return `thought for ${formatReasoningDuration(duration)}`;
    return "thought";
  }
  return "thinking";
}

function reasoningDurationMs(blocks: ReasoningBlock[]): number | null {
  const starts = blocks.map((block) => parseTimestamp(block.startedAt)).filter((time): time is number => time != null);
  const ends = blocks.map((block) => parseTimestamp(block.completedAt)).filter((time): time is number => time != null);
  if (!starts.length || !ends.length) return null;
  const started = Math.min(...starts);
  const completed = Math.max(...ends);
  if (completed <= started) return null;
  return completed - started;
}

function formatReasoningDuration(ms: number): string {
  const seconds = Math.max(1, Math.round(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
}

type ToolRenderState = {
  expanded: Set<string>;
  hoveredId: string | null;
  onHover: (toolId: string | null) => void;
  onToggle: (toolId: string) => void;
};

function renderTools(
  opentui: any,
  ctx: any,
  theme: Theme,
  container: any,
  tools: ToolCallView[],
  tick: number,
  state: ToolRenderState,
  lineWidth: number,
): void {
  if (!container) return;

  // Mutate in place when the count hasn't changed (the in-place rule from
  // DESIGN_TOKENS.md §4.2: the same row that said `⠋ search …` becomes
  // `✓ search …`. No append. No second row.)
  const children = childrenOf(container);
  if (children.length === tools.length) {
    for (let i = 0; i < tools.length; i++) {
      updateToolNode(children[i], tools[i]!, tick, theme, state, lineWidth);
    }
    return;
  }

  // Count changed — rebuild.
  for (const child of childrenOf(container)) container.remove?.(child.id ?? child);
  for (const tool of tools) {
    const row = makeText(opentui, ctx, { content: "", fg: toolColor(theme, tool), flexShrink: 0, cursor: "pointer" });
    attachToolHandlers(row, tool, state);
    updateToolNode(row, tool, tick, theme, state, lineWidth);
    container.add?.(row);
  }
}

function attachToolHandlers(row: any, tool: ToolCallView, state: ToolRenderState): void {
  row.onMouseOver = () => state.onHover(tool.id);
  row.onMouseOut = () => {
    if (state.hoveredId === tool.id) state.onHover(null);
  };
  row.onMouseDown = (event: any) => {
    if (isPrimaryDown(event)) state.onToggle(tool.id);
  };
}

function updateToolNode(row: any, tool: ToolCallView, tick: number, theme: Theme, state: ToolRenderState, lineWidth: number): void {
  if (row.content !== undefined) row.content = renderToolLine(tool, tick, state.expanded.has(tool.id), state.hoveredId === tool.id, lineWidth);
  if ("fg" in row) row.fg = toolColor(theme, tool);
  attachToolHandlers(row, tool, state);
}

function renderToolLine(tool: ToolCallView, tick: number, expanded: boolean, hovered: boolean, lineWidth: number): string {
  const hover = hovered ? glyphs.hover : " ";
  const icon = toolIcon(tool.status, tick);
  const name = toolLaneName(tool, TOOL_NAME_LANE);
  const args = tool.argsSummary || "";
  const outputVisible = toolOutputVisible(tool, expanded);
  const hint = tool.output && !outputVisible ? ` · ${outputSummary(tool.output)}` : "";
  const output = tool.output && outputVisible ? formatToolOutput(tool.output) : "";
  const line = `${hover} ${icon} ${name} ${args}${hint}`;
  return `${withRightMeta(line, toolMeta(tool), lineWidth)}${output}`;
}

function toolOutputVisible(tool: ToolCallView, expanded: boolean): boolean {
  if (!tool.output) return false;
  if (expanded) return true;
  return tool.status === "done" && outputLineCount(tool.output) <= 2 && trimOutput(tool.output).length <= 220;
}

function formatToolOutput(output: string): string {
  if (!output) return "";
  const indent = " ".repeat(2 + 1 + 1 + TOOL_NAME_LANE + 1);
  return trimOutput(output)
    .split("\n")
    .map((line) => `\n${indent}${glyphs.treeBranch} ${line}`)
    .join("");
}

function outputSummary(output: string): string {
  const lines = output.split("\n").filter(Boolean).length || 1;
  return `${lines} line${lines === 1 ? "" : "s"}`;
}

function toolContainerHeight(tools: ToolCallView[], expandedTools: Set<string>): number {
  return tools.reduce((height, tool) => height + 1 + (toolOutputVisible(tool, expandedTools.has(tool.id)) ? outputLineCount(tool.output) : 0), 0);
}

function outputLineCount(output: string): number {
  return output.split("\n").filter(Boolean).length || 1;
}

function toolMeta(tool: ToolCallView): string {
  if (tool.status === "running") return "running…";
  const duration = durationMs(tool.startedAt, tool.completedAt);
  if (duration == null) return "";
  if (duration < 10_000) return `${(duration / 1000).toFixed(1)}s`;
  return `${Math.round(duration / 1000)}s`;
}

function durationMs(start: string | undefined, end: string | undefined): number | null {
  if (!start || !end) return null;
  const started = Date.parse(start);
  const completed = Date.parse(end);
  if (!Number.isFinite(started) || !Number.isFinite(completed) || completed < started) return null;
  return completed - started;
}

function withRightMeta(left: string, meta: string, width: number): string {
  if (!meta) return left;
  const gap = 2;
  const maxLeft = Math.max(0, width - meta.length - gap);
  const clipped = truncateEnd(left, maxLeft);
  return `${clipped}${" ".repeat(Math.max(gap, width - clipped.length - meta.length))}${meta}`;
}

function truncateEnd(value: string, max: number): string {
  if (value.length <= max) return value;
  if (max <= 1) return value.slice(0, max);
  return `${value.slice(0, max - 1)}…`;
}

function isPrimaryDown(event: any): boolean {
  return event?.type === "down" && (event.button === 0 || event.button == null);
}

function toolIcon(status: string, tick: number): string {
  if (status === "running") return spinnerBeatFrame("braille", tick);
  if (status === "done") return glyphs.toolOk;
  if (status === "failed") return glyphs.toolFail;
  if (status === "blocked") return glyphs.toolBlock;
  if (status === "cancelled") return glyphs.toolSkip;
  return glyphs.system;
}

function toolColor(theme: Theme, tool: ToolCallView): string {
  if (tool.status === "failed") return theme.toolFail;
  if (tool.status === "blocked") return theme.warning;
  if (tool.status === "cancelled") return theme.textSubtle;
  if (tool.status === "done") return theme.toolOk;
  // Running / unstarted = the quieter "idle" color. Tools no longer paint
  // hard-orange before resolving (DESIGN_TOKENS.md §3 "critical change").
  return theme.toolIdle;
}

function trimOutput(output: string): string {
  const flat = output.replace(/\s+\n/g, "\n");
  const limit = 600;
  if (flat.length <= limit) return flat;
  return `${flat.slice(0, limit)} … (+${flat.length - limit} bytes)`;
}

function childrenOf(node: any): any[] {
  if (typeof node?.getChildren === "function") return node.getChildren();
  return Array.isArray(node?.children) ? node.children : [];
}

function removeRenderable(parent: any, child: any): void {
  if (!parent || !child) return;
  parent.remove?.(child.id ?? child);
}

function splitAssistantAroundPatch(text: string, width: number, hasPatch: boolean): { lead: string; tail: string } {
  if (!text) return { lead: "", tail: "" };
  if (!hasPatch) return { lead: plainMarkdown(text, width), tail: "" };
  const paragraphs = text.split(/\n{2,}/);
  const splitIndex = paragraphs.findIndex((paragraph) => /\bpatch[:.]?\s*$/i.test(paragraph.trim()) || /\bhere is (?:the )?patch[:.]?\s*$/i.test(paragraph.trim()));
  if (splitIndex < 0 || splitIndex >= paragraphs.length - 1) return { lead: plainMarkdown(text, width), tail: "" };
  return {
    lead: plainMarkdown(paragraphs.slice(0, splitIndex + 1).join("\n\n"), width),
    tail: plainMarkdown(paragraphs.slice(splitIndex + 1).join("\n\n"), width),
  };
}

type InlineDiffPreview = {
  header: string;
  body: string;
};

function diffPreview(diff: DiffState | null, width: number): InlineDiffPreview | null {
  if (!diff?.text) return null;
  const path = diff.paths[0] ?? firstDiffPath(diff.text) ?? "diff";
  const counts = diffCounts(diff.text);
  const body = renderDiffExcerpt(diff.text);
  if (!body) return null;
  const suffix = diff.truncated ? " · truncated" : "";
  const meta = `+${counts.added}  ${glyphs.minus}${counts.removed}  ${glyphs.kbdL}⏎${glyphs.kbdR} apply  ${glyphs.kbdL}d${glyphs.kbdR} diff${suffix}`;
  const maxPath = Math.max(8, width - meta.length - "PATCH  ".length - 2);
  return {
    header: withRightMeta(`PATCH  ${truncateMiddle(path, maxPath)}`, meta, width),
    body,
  };
}

function firstDiffPath(text: string): string | null {
  const match = text.match(/^diff --git a\/\S+ b\/(\S+)/m);
  if (match?.[1]) return match[1];
  const file = text.match(/^\+\+\+ b\/(.+)$/m);
  return file?.[1] ?? null;
}

function diffCounts(text: string): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const line of text.split("\n")) {
    if (line.startsWith("+++") || line.startsWith("---")) continue;
    if (line.startsWith("+")) added += 1;
    else if (line.startsWith("-")) removed += 1;
  }
  return { added, removed };
}

function renderDiffExcerpt(text: string): string {
  const lines = text.split("\n");
  const hunkIndex = lines.findIndex((line) => line.startsWith("@@"));
  if (hunkIndex === -1) return lines.filter(Boolean).slice(0, PATCH_PREVIEW_LINES).join("\n");

  const hunk = lines[hunkIndex]!;
  const header = hunk.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
  let oldLine = header ? Number(header[1]) : 0;
  let newLine = header ? Number(header[2]) : 0;
  const rendered: string[] = [];

  for (const line of lines.slice(hunkIndex + 1)) {
    if (rendered.length >= PATCH_PREVIEW_LINES) break;
    if (!line || line.startsWith("\\ No newline")) continue;
    const marker = line[0]!;
    const text = line.slice(1);
    if (marker === "+") {
      rendered.push(`${String(newLine).padStart(4)} +  ${text}`);
      newLine += 1;
    } else if (marker === "-") {
      rendered.push(`${String(oldLine).padStart(4)} -  ${text}`);
      oldLine += 1;
    } else if (marker === " ") {
      rendered.push(`${String(newLine).padStart(4)}    ${text}`);
      oldLine += 1;
      newLine += 1;
    }
  }

  return rendered.join("\n");
}

function truncateMiddle(value: string, max: number): string {
  if (value.length <= max) return value;
  const keep = Math.max(1, Math.floor((max - 1) / 2));
  const tail = Math.max(1, max - keep - 1);
  return `${value.slice(0, keep)}…${value.slice(value.length - tail)}`;
}
