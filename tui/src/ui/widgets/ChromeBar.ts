import { spinnerBeatFrame } from "../../design/spinners";
import { glyphs } from "../../design/glyphs";
import type { AppState, AppPhase } from "../../state/reducer";
import type { Theme } from "../theme";
import { isCompactViewport, makeBox, makeText } from "../layout";

// The chrome bar is the only persistent top fixture (DESIGN_TOKENS.md §4.1.1).
// It carries identity (workspace · model · branch), live state (spinner +
// phase pill + transient pill stack), and the ctx meter.
//
// Implementation note: opentui's plain-text capture strips background-color
// styling, so the ctx meter is built from unicode block characters (▰▱)
// rather than overlapping background-only Boxes. This also reads better on
// terminals without truecolor support.

const ASSUMED_CONTEXT_WINDOW = 128_000;
const WARN_THRESHOLD = 80;
const DANGER_THRESHOLD = 95;
const METER_WIDTH = 5;
const SPINNER_WIDTH = 3;
const FLEX_BUDGET_SAFETY = 8;
const QUIET_CTX_FLEX_BUDGET_SAFETY = 16;
const COMPACT_FLEX_BUDGET_SAFETY = 1;
const PAPER_FLEX_BUDGET_SAFETY = 2;

const METER_FILLED = "▰";
const METER_EMPTY = "▱";
const SEP = "│";
const WIDE_SEP = `  ${SEP}  `;
const TIGHT_SEP = ` ${SEP} `;
const APP_MARK = `${glyphs.bulletDiamond} tinyagent`;

type PillKind = "approval" | "update" | "compact" | "plan";
export type ChromeAction = "sessions" | "model" | "diff" | "usage" | "update" | "review" | "approval";
type HitSegment = { start: number; end: number; action: ChromeAction };
type ChromePill = { kind: PillKind; label: string; fg: string; bg: string };

export class ChromeBarWidget {
  readonly node: any;
  private tick = 0;
  private leftSegments: HitSegment[] = [];
  private transientSegments: HitSegment[] = [];
  private phaseAction: ChromeAction | null = null;
  private hoveredLeftAction: ChromeAction | null = null;
  private lastState: AppState | null = null;
  private lastViewportWidth: number | undefined;
  private onAction: ((action: ChromeAction) => void) | null = null;

  // Left section assembled into a single text node so glyph spacing is exact.
  private leftText: any;

  // Right section split into spinner, phase pill, transient pill stack, ctx meter.
  private spinnerText: any;
  private phasePill: any;
  private transientText: any;
  private ctxText: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      height: 1,
      width: "100%",
      flexDirection: "row",
      paddingX: 1,
      backgroundColor: theme.surfaceMuted ?? theme.surface,
      flexShrink: 0,
    });

    this.leftText = makeText(opentui, ctx, { content: "", fg: theme.text, cursor: "pointer" });
    this.leftText.onMouseDown = (event: any) => this.handleTextHit(event, this.leftText, this.leftSegments);
    this.leftText.onMouseMove = (event: any) => this.handleLeftHover(event);
    this.leftText.onMouseOver = (event: any) => this.handleLeftHover(event);
    this.leftText.onMouseOut = () => this.setHoveredLeftAction(null);
    this.node.add?.(this.leftText);

    // Flex spacer
    this.node.add?.(makeBox(opentui, ctx, { flexGrow: 1, minWidth: 1 }));

    this.spinnerText = makeText(opentui, ctx, { content: " ", fg: theme.success });
    this.node.add?.(this.spinnerText);

    this.phasePill = makeText(opentui, ctx, { content: "", fg: theme.textMuted, cursor: "pointer" });
    this.phasePill.onMouseDown = (event: any) => {
      if (!isPrimaryDown(event) || !this.phaseAction) return;
      this.activate(this.phaseAction);
    };
    this.node.add?.(this.phasePill);

    this.transientText = makeText(opentui, ctx, { content: "", fg: theme.textMuted, cursor: "pointer" });
    this.transientText.onMouseDown = (event: any) => this.handleTextHit(event, this.transientText, this.transientSegments);
    this.node.add?.(this.transientText);

    this.ctxText = makeText(opentui, ctx, { content: "", fg: theme.text, cursor: "pointer" });
    this.ctxText.onMouseDown = (event: any) => {
      if (isPrimaryDown(event)) this.activate("usage");
    };
    this.node.add?.(this.ctxText);
  }

  setOnAction(handler: (action: ChromeAction) => void): void {
    this.onAction = handler;
  }

  activate(action: ChromeAction): void {
    this.onAction?.(action);
  }

  update(state: AppState, viewportWidth?: number): void {
    this.tick = (this.tick + 1) % 1_000_000;
    this.lastState = state;
    this.lastViewportWidth = viewportWidth;

    // ── Identity (left) — single text line, fixed spacing
    const workspace = state.workspaces.find((w) => w.workspace_id === state.activeWorkspaceId);
    const branch = state.activeSession?.git?.branch ?? "—";

    // Compute the actual right-side width so we don't over-reserve under
    // compact terminals. Each transient pill adds its rendered text length.
    const transientsForBudget = collectTransients(state, this.theme);
    const measuredWidth = numericWidth(this.node?.width) ?? numericWidth(this.node?.computedWidth);
    const totalWidth = measuredWidth ?? viewportWidth ?? 120;
    const compactCtx = isCompactViewport(totalWidth);
    const transientWidth = renderTransientPills(transientsForBudget).text.length;
    const phaseWidth = ` ${glyphs.pillL} ${phaseLabel(state.phase, state.sessionMode)} ${glyphs.pillR}`.length;
    const tokens = state.activeSession?.usage?.totalTokens ?? 0;
    const pct = contextPercent(tokens);
    const ctxMeter = renderCtxMeter(pct, compactCtx);
    const ctxWidth = ctxMeter.text.length;
    const flexSafety = compactCtx
      ? COMPACT_FLEX_BUDGET_SAFETY
      : totalWidth <= 110 && ctxMeter.tone === "brand"
        ? PAPER_FLEX_BUDGET_SAFETY
        : ctxMeter.tone === "brand"
          ? QUIET_CTX_FLEX_BUDGET_SAFETY
          : FLEX_BUDGET_SAFETY;
    const rightReserve = SPINNER_WIDTH + phaseWidth + ctxWidth + transientWidth + flexSafety;
    const budget = Math.max(20, totalWidth - rightReserve);
    const workspaceName = workspace?.name ?? "—";
    const left = plainLeft(state, workspaceName, branch, budget, this.hoveredLeftAction === "diff", !compactCtx, compactCtx);
    this.setText(this.leftText, left);
    this.leftSegments = identitySegments(left, workspaceName, state.model, branch);

    // ── Spinner — braille only when phase is animating
    const animating = state.phase === "thinking" || state.phase === "streaming";
    this.setText(this.spinnerText, animating ? ` ${spinnerBeatFrame("braille", this.tick)} ` : " ".repeat(SPINNER_WIDTH));
    this.setColor(this.spinnerText, phaseStyle(state.phase, state.sessionMode, this.theme).fg);

    // ── Phase pill — always present
    const phase = phaseStyle(state.phase, state.sessionMode, this.theme);
    this.setText(this.phasePill, ` ${glyphs.pillL} ${phaseLabel(state.phase, state.sessionMode)} ${glyphs.pillR}`);
    this.setColor(this.phasePill, phase.fg);
    this.setBg(this.phasePill, phase.bg);
    this.phaseAction = phaseAction(state.phase);

    // ── Transient pills — collapsed into a single text node so spacing is
    // consistent regardless of how many pills are active.
    const transients = collectTransients(state, this.theme);
    if (transients.length === 0) {
      this.setText(this.transientText, "");
      this.transientSegments = [];
      this.setBg(this.transientText, undefined);
    } else {
      const rendered = renderTransientPills(transients);
      const txt = rendered.text;
      this.setText(this.transientText, txt);
      this.transientSegments = rendered.segments;
      // Color follows the most urgent transient (danger-ctx > approval > update > plan).
      this.setColor(this.transientText, transients[0]!.fg);
      this.setBg(this.transientText, transients[0]!.bg);
    }

    // ── Ctx meter — block characters so it shows up in plain text
    this.setText(this.ctxText, ctxMeter.text);
    this.setColor(this.ctxText, ctxColor(ctxMeter.tone, this.theme));
  }

  private setText(node: any, value: string): void {
    if (!node) return;
    if ("content" in node) node.content = value;
  }

  private setColor(node: any, color: string): void {
    if (!node) return;
    if ("fg" in node) node.fg = color;
  }

  private setBg(node: any, color: string | undefined): void {
    if (!node) return;
    if ("bg" in node) node.bg = color;
  }

  private handleTextHit(event: any, node: any, segments: HitSegment[]): void {
    if (!isPrimaryDown(event)) return;
    const offset = textOffset(event, node);
    const segment = segmentAtOffset(segments, offset);
    if (segment) this.activate(segment.action);
  }

  private handleLeftHover(event: any): void {
    const offset = textOffset(event, this.leftText);
    const action = segmentAtOffset(this.leftSegments, offset)?.action ?? null;
    this.setHoveredLeftAction(action);
  }

  private setHoveredLeftAction(action: ChromeAction | null): void {
    if (this.hoveredLeftAction === action) return;
    this.hoveredLeftAction = action;
    if (this.lastState) this.update(this.lastState, this.lastViewportWidth);
  }
}

function isPrimaryDown(event: any): boolean {
  return event?.type === "down" && (event.button === 0 || event.button == null);
}

function textOffset(event: any, node: any): number {
  const x = typeof event?.x === "number" ? event.x : 0;
  const nodeX = numericPosition(node?.computedX) ?? numericPosition(node?.x) ?? numericPosition(node?.left) ?? 0;
  return Math.max(0, Math.floor(x - nodeX));
}

function numericPosition(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function segmentAtOffset(segments: HitSegment[], offset: number): HitSegment | undefined {
  return segments.find((item) => offset >= item.start && offset < item.end);
}

function plainLeft(_state: AppState, workspace: string, branch: string, budget: number, expandBranch = false, preserveLabels = true, compact = false): string {
  // Build the wayfinding row, then progressively shorten/drop the branch
  // before dropping the model. This preserves the spec invariant that the
  // model is the most stable wayfinding field under width pressure.
  const buildShort = (branchTrunc: number | null, includeModel: boolean, includeLabels: boolean, sep = WIDE_SEP): string => {
    const ws = includeLabels ? `ws : ${workspace}` : workspace;
    const model = includeLabels ? `model : ${_state.model}` : _state.model;
    const parts = [
      APP_MARK,
      ws,
      ...(includeModel ? [model] : []),
      ...(branchTrunc == null ? [] : [`${glyphs.branch} ${truncateMiddle(branch, branchTrunc)}`]),
    ];
    return parts.join(sep);
  };
  if (compact && !expandBranch) {
    const collapsedBranch = buildShort(3, true, false);
    if (collapsedBranch.length <= budget) return collapsedBranch;
  }
  if (expandBranch) {
    const branchLens = compact ? [8, 3] : [28, 20, 14, 8, 3];
    for (const branchLen of branchLens) {
      const candidate = buildShort(branchLen, true, false);
      if (candidate.length <= budget) return candidate;
    }
    for (const branchLen of compact ? [8] : [20, 14, 8]) {
      const candidate = buildShort(branchLen, false, false);
      if (candidate.length <= budget) return candidate;
    }
  }
  for (const branchLen of [28, 20, 14, 8, 3]) {
    const candidate = buildShort(branchLen, true, true);
    if (candidate.length <= budget) return candidate;
  }
  const labeledNoBranch = buildShort(null, true, true);
  if (preserveLabels && candidateShouldKeepLabels(budget, labeledNoBranch)) return labeledNoBranch;
  const tightLabeledNoBranch = buildShort(null, true, true, TIGHT_SEP);
  if (preserveLabels && candidateShouldKeepLabels(budget, tightLabeledNoBranch)) return tightLabeledNoBranch;
  for (const branchLen of [28, 20, 14, 3]) {
    const candidate = buildShort(branchLen, true, false);
    if (candidate.length <= budget) return candidate;
  }
  const modelOnly = buildShort(null, true, false);
  if (modelOnly.length <= budget) return modelOnly;
  // Drop model under extreme pressure.
  for (const branchLen of [20, 14, 8]) {
    const candidate = buildShort(branchLen, false, false);
    if (candidate.length <= budget) return candidate;
  }
  // Last resort — preserve the model over the workspace. The active model is
  // the more stable wayfinding field when transient state consumes the bar.
  return [APP_MARK, _state.model].join(WIDE_SEP);
}

function candidateShouldKeepLabels(budget: number, candidate: string): boolean {
  return candidate.length <= budget && budget >= 52;
}

function identitySegments(text: string, workspace: string, model: string, branch: string): HitSegment[] {
  const segments: HitSegment[] = [];
  let offset = 0;
  for (const part of text.split(/\s+│\s+/u)) {
    const start = text.indexOf(part, offset);
    const end = start + part.length;
    if (part === `ws : ${workspace}` || part === `ws:${workspace}` || part === workspace) {
      segments.push({ start, end, action: "sessions" });
    } else if (part === `model : ${model}` || part === `model:${model}` || part === model) {
      segments.push({ start, end, action: "model" });
    } else if (part.startsWith(`${glyphs.branch} `)) {
      segments.push({ start, end, action: "diff" });
    }
    offset = end;
  }
  return segments;
}

function renderTransientPills(transients: ChromePill[]): {
  text: string;
  segments: HitSegment[];
} {
  let text = "";
  const segments: HitSegment[] = [];
  const visible = transients.slice(0, 2);
  for (const transient of visible) {
    const action = transientAction(transient.kind);
    const pill = ` ${glyphs.pillL} ${transient.label} ${glyphs.pillR}`;
    const start = text.length;
    text += pill;
    if (action) segments.push({ start, end: text.length, action });
  }
  const overflow = transients.length - visible.length;
  if (overflow > 0) {
    const pill = ` ${glyphs.pillL} +${overflow} ${glyphs.pillR}`;
    const start = text.length;
    text += pill;
    segments.push({ start, end: text.length, action: "usage" });
  }
  return { text, segments };
}

function transientAction(kind: PillKind): ChromeAction | null {
  if (kind === "approval") return "approval";
  if (kind === "update") return "update";
  if (kind === "compact") return "usage";
  return null;
}

function phaseAction(phase: AppPhase): ChromeAction | null {
  if (phase === "approval") return "approval";
  if (phase === "failed") return "review";
  return null;
}

function collectTransients(state: AppState, theme: Theme): ChromePill[] {
  const out: ChromePill[] = [];
  const tokens = state.activeSession?.usage?.totalTokens ?? 0;
  const pct = contextPercent(tokens);
  // Order matters: most urgent first so the text-color choice tracks severity.
  if (pct >= DANGER_THRESHOLD) out.push({ kind: "compact", label: "compact", fg: theme.danger, bg: theme.dangerSoft });
  if (state.activeSession?.pendingApproval && state.phase !== "approval")
    out.push({ kind: "approval", label: "approve queued", fg: theme.warning, bg: theme.warningSoft });
  if (state.updatePanel.result?.available)
    out.push({ kind: "update", label: `update ${state.updatePanel.result.latest_version}`, fg: theme.accent, bg: theme.accentSoft });
  if (state.sessionMode === "plan" && state.phase !== "idle") out.push({ kind: "plan", label: "plan", fg: theme.warning, bg: theme.warningSoft });
  return out;
}

type CtxTone = "brand" | "warning" | "danger";

function contextPercent(tokens: number): number {
  return Math.min(100, Math.round((tokens / ASSUMED_CONTEXT_WINDOW) * 100));
}

function ctxTone(pct: number): CtxTone {
  if (pct >= DANGER_THRESHOLD) return "danger";
  if (pct >= WARN_THRESHOLD) return "warning";
  return "brand";
}

function ctxColor(tone: CtxTone, theme: Theme): string {
  if (tone === "danger") return theme.danger;
  if (tone === "warning") return theme.warning;
  return theme.accent;
}

function renderCtxMeter(pct: number, compact: boolean): { text: string; tone: CtxTone } {
  const tone = ctxTone(pct);
  if (compact) return { text: `  ${pct}%`, tone };
  const filled = Math.max(0, Math.min(METER_WIDTH, Math.round((pct / 100) * METER_WIDTH)));
  const bar = METER_FILLED.repeat(filled) + METER_EMPTY.repeat(METER_WIDTH - filled);
  const pctText = `${pct.toString().padStart(2)}%`;
  const suffix = tone === "brand" ? "" : ` — ${tone}`;
  return { text: `  ${SEP}  ctx ${bar} ${pctText}${suffix}`, tone };
}

function phaseLabel(phase: AppPhase, mode: string): string {
  if (phase === "approval") return "approve";
  if (phase === "failed") return "failed";
  if (phase === "thinking") return "thinking";
  if (phase === "streaming") return "streaming";
  if (mode === "plan") return "plan";
  return "idle";
}

function phaseStyle(phase: AppPhase, mode: string, theme: Theme): { fg: string; bg: string } {
  if (phase === "approval") return { fg: theme.warning, bg: theme.warningSoft };
  if (phase === "failed") return { fg: theme.danger, bg: theme.dangerSoft };
  if (phase === "streaming" || phase === "thinking") return { fg: theme.accent, bg: theme.accentSoft };
  if (mode === "plan") return { fg: theme.warning, bg: theme.warningSoft };
  return { fg: theme.textMuted, bg: theme.surfaceMuted };
}

function truncateMiddle(value: string, max: number): string {
  if (value.length <= max) return value;
  if (max <= 3) return "…";
  const keep = max - 1;
  const left = Math.ceil(keep / 2);
  const right = Math.floor(keep / 2);
  return `${value.slice(0, left)}…${value.slice(-right)}`;
}

function numericWidth(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}
