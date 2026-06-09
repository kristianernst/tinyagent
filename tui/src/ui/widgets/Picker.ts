import { pickerCommands, type CommandId } from "../../commands";
import { glyphs } from "../../design/glyphs";
import type { MentionCandidate, MentionDetection } from "../mentions";
import type { MentionTrigger } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

// One picker, three trigger modes (DESIGN_TOKENS.md §4.4). This is the only
// interactive picker surface. Anchored above the composer,
// grows upward, max ~12 rows, clamped to the viewport. Mouse hover selects a
// row directly; keyboard selection stays on the explicit selectedIndex lane.
//
// Triggers:
//   "/"  slash commands (run by id)
//   "@"  files & directories (inserted into composer)
//   "$"  skills (inserted into composer)
//
// Modes share visuals, only the badge + dataset differ.

export type PickerCandidate = MentionCandidate;
export type PickerSelect = (candidate: PickerCandidate, trigger: MentionTrigger) => void;
export type PickerCommandSelect = (id: CommandId) => void;

const TRIGGER_BADGE: Record<MentionTrigger, string> = {
  "/": "/",
  "@": "@",
  $: "$",
};

const TRIGGER_TITLE: Record<MentionTrigger, string> = {
  "/": "commands",
  "@": "files",
  $: "skills",
};

const PICKER_CONTENT_WIDTH = 68;
const MARKER_WIDTH = 2;
const LABEL_WIDTH = 16;
const CUE_WIDTH = 2;
const COMMAND_VISIBLE_LIMIT = 5;
const COMMAND_PALETTE_VISIBLE_LIMIT = 9;
const SKILL_VISIBLE_LIMIT = 3;

export class PickerWidget {
  readonly node: any;
  private header: any;
  private optionsBox: any;
  private badge: any;
  private titleText: any;
  private countText: any;
  private hintWrap: any;
  private hintRow: any;
  private emptyRow: any;
  private rows: any[] = [];
  private selectedIndex = 0;
  private hoverIndex: number | null = null;

  private trigger: MentionTrigger = "/";
  private query = "";
  private candidates: PickerCandidate[] = [];
  private pickHandler: PickerSelect | null = null;

  // Slash-only mode: when opened as a full command palette (Ctrl+K),
  // selecting a row fires a CommandId instead of an insert.
  private commandHandler: PickerCommandSelect | null = null;
  private commandMode = false;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "rounded",
      border: true,
      borderColor: theme.borderStrong ?? theme.border,
      paddingX: 0,
      paddingY: 0,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
      visible: false,
      position: "absolute",
      // Composer (3 rows: border+body+border) + hint row + 1 cell breathing room.
      // Picker grows upward from this anchor and never overlaps the composer.
      // The Paper spec wants a compact popover, not a full-width rail.
      bottom: 6,
      left: 2,
      width: 72,
      minWidth: 42,
      maxWidth: 72,
      maxHeight: 16,
      minHeight: 4,
      zIndex: 80,
    });

    // Header strip: ⦗ / ⦘ commands · 5 / 19
    this.header = makeBox(opentui, ctx, {
      flexDirection: "row",
      height: 1,
      paddingX: 1,
      backgroundColor: theme.surface,
      flexShrink: 0,
    });
    this.badge = makeText(opentui, ctx, {
      content: ` ${glyphs.pillL} / ${glyphs.pillR} `,
      fg: theme.accent,
      bg: theme.accentSoft,
    });
    this.header.add?.(this.badge);
    this.titleText = makeText(opentui, ctx, { content: " commands", fg: theme.textMuted, marginLeft: 1 });
    this.header.add?.(this.titleText);
    this.header.add?.(makeBox(opentui, ctx, { flexGrow: 1 }));
    this.countText = makeText(opentui, ctx, { content: "", fg: theme.textSubtle });
    this.header.add?.(this.countText);
    this.node.add?.(this.header);

    this.optionsBox = makeBox(opentui, ctx, {
      flexDirection: "column",
      paddingY: 0,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
      minHeight: 1,
      maxHeight: 10,
      flexShrink: 0,
    });
    this.node.add?.(this.optionsBox);

    // Hint row — kept inside the picker frame, padded so it doesn't kiss the
    // left border. We also draw a thin divider above it so the hint reads as
    // chrome, not as another row.
    this.hintWrap = makeBox(opentui, ctx, {
      flexDirection: "column",
      paddingX: 1,
      flexShrink: 0,
      borderStyle: "single",
      border: ["top"],
      borderColor: theme.border,
    });
    this.hintRow = makeText(opentui, ctx, {
      content: hintLine("insert"),
      fg: theme.textSubtle,
      flexShrink: 0,
    });
    this.hintWrap.add?.(this.hintRow);
    this.node.add?.(this.hintWrap);

    this.emptyRow = makeText(opentui, ctx, {
      content: "",
      fg: theme.textSubtle,
      flexShrink: 0,
      marginX: 1,
      visible: false,
      enableLayout: false,
    });
    this.node.add?.(this.emptyRow);
  }

  /** Open as one of the three mention pickers. */
  open(detection: MentionDetection, candidates: PickerCandidate[], onPick: PickerSelect): void {
    this.commandMode = false;
    this.commandHandler = null;
    this.trigger = detection.trigger;
    this.query = detection.query;
    this.candidates = candidates;
    this.pickHandler = onPick;
    this.selectedIndex = preferredCandidateIndex(detection, candidates);
    this.hoverIndex = null;

    this.applyHeader(detection.trigger, detection.query, candidates);
    this.applyOptions(candidates);

    this.setVisible(true);
  }

  /** Open as the full command palette (Ctrl+K). All commands available. */
  openCommandPalette(onPick: PickerCommandSelect): void {
    this.commandMode = true;
    this.commandHandler = onPick;
    this.pickHandler = null;
    this.trigger = "/";
    this.query = "";
    this.candidates = pickerCommands.map((c) => ({ label: `/${c.id}`, description: c.title, insert: `/${c.id} ` }));
    this.selectedIndex = 0;
    this.hoverIndex = null;

    this.applyHeader("/", "", this.candidates);
    this.applyOptions(this.candidates);

    this.setVisible(true);
  }

  refresh(detection: MentionDetection, candidates: PickerCandidate[]): void {
    this.trigger = detection.trigger;
    this.query = detection.query;
    this.candidates = candidates;
    this.selectedIndex = preferredCandidateIndex(detection, candidates);
    this.hoverIndex = this.hoverIndex == null ? null : Math.min(this.hoverIndex, Math.max(0, candidates.length - 1));
    this.applyHeader(detection.trigger, detection.query, candidates);
    this.applyOptions(candidates);
    this.setVisible(true);
  }

  hide(): void {
    this.setVisible(false);
    this.candidates = [];
    this.pickHandler = null;
    this.commandHandler = null;
    this.commandMode = false;
    this.selectedIndex = 0;
    this.hoverIndex = null;
    this.query = "";
  }

  isVisible(): boolean {
    return Boolean(this.node?.visible);
  }

  candidateCount(): number {
    return this.candidates.length;
  }

  moveUp(): void {
    if (!selectableCount(this.candidates)) return;
    this.selectedIndex = nextSelectableIndex(this.candidates, this.selectedIndex, -1);
    this.applyHeader(this.trigger, this.query, this.candidates);
    this.applyOptions(this.candidates);
  }

  moveDown(): void {
    if (!selectableCount(this.candidates)) return;
    this.selectedIndex = nextSelectableIndex(this.candidates, this.selectedIndex, 1);
    this.applyHeader(this.trigger, this.query, this.candidates);
    this.applyOptions(this.candidates);
  }

  setHoverIndex(index: number | null): void {
    if (index == null || index < 0 || index >= this.candidates.length || !isSelectable(this.candidates[index])) {
      this.hoverIndex = null;
    } else {
      this.hoverIndex = index;
    }
    this.applyOptions(this.candidates);
  }

  pickFirst(): boolean {
    if (!this.candidates.length) return false;
    return this.commit({ value: this.candidates[0]!.label });
  }

  /** Commit the currently highlighted row. Returns true if a candidate fired. */
  commit(event?: any): boolean {
    if (!selectableCount(this.candidates)) return false;
    let candidate: PickerCandidate | undefined;
    if (event && typeof event.index === "number") {
      candidate = this.candidates[event.index];
    }
    if (event && event.value) {
      candidate = this.candidates.find((c) => c.label === event.value);
    }
    if (!candidate) {
      candidate = this.candidates[this.selectedIndex] ?? this.candidates[0];
    }
    if (!isSelectable(candidate)) return false;
    if (this.commandMode && this.commandHandler) {
      // Slash command palette mode — strip the leading "/" and emit CommandId.
      const id = candidate.label.replace(/^\//, "") as CommandId;
      this.commandHandler(id);
      return true;
    }
    if (this.pickHandler) {
      this.pickHandler(candidate, this.trigger);
      return true;
    }
    return false;
  }

  private setVisible(visible: boolean): void {
    if (!this.node) return;
    if ("visible" in this.node) this.node.visible = visible;
    if ("enableLayout" in this.node) this.node.enableLayout = visible;
  }

  private applyHeader(trigger: MentionTrigger, query: string, candidates: PickerCandidate[]): void {
    const count = selectableCount(candidates);
    if (this.badge && "content" in this.badge) {
      this.badge.content = ` ${glyphs.pillL} ${TRIGGER_BADGE[trigger]} ${glyphs.pillR} `;
    }
    if (this.titleText && "content" in this.titleText) {
      this.titleText.content = trigger === "@" && query ? ` ${TRIGGER_TITLE[trigger]} matching ${query}` : ` ${TRIGGER_TITLE[trigger]}`;
    }
    if (this.countText && "content" in this.countText) {
      if (count <= 0) {
        this.countText.content = "";
      } else if (trigger === "@") {
        this.countText.content = `${count} `;
      } else if (trigger === "$") {
        this.countText.content = `${Math.min(SKILL_VISIBLE_LIMIT, count)} / ${count} `;
      } else {
        this.countText.content = `${selectedOrdinal(candidates, this.selectedIndex)} / ${count} `;
      }
    }
  }

  private applyOptions(candidates: PickerCandidate[]): void {
    if (!this.optionsBox) return;
    for (const row of this.rows) this.optionsBox.remove?.(row.id ?? row);
    this.rows = [];
    if (candidates.length === 0) {
      // Empty state is rendered as a *label* (in the hint row), not a
      // selectable option. We collapse the chrome + options list so keyboard
      // nav can't land on a phantom row and the popover is the single quiet
      // row promised by DESIGN_TOKENS.md §4.4.
      this.setCollapsedEmptyState(true);
      this.setOptionsVisible(false);
      if (this.emptyRow && "content" in this.emptyRow) {
        this.emptyRow.content = `no matches · ${glyphs.kbdL}esc${glyphs.kbdR} cancel`;
      }
      return;
    }
    this.setCollapsedEmptyState(false);
    this.setOptionsVisible(true);
    // Mention pickers stay compact like the Paper reference. When the query
    // matches a row deep in the dataset, show a small window around that row
    // instead of collapsing the picker to a one-item filtered list.
    const visibleLimit = this.commandMode
      ? COMMAND_PALETTE_VISIBLE_LIMIT
      : this.trigger === "$"
        ? SKILL_VISIBLE_LIMIT
        : COMMAND_VISIBLE_LIMIT;
    const window = visibleCandidateWindow(candidates.length, this.selectedIndex, visibleLimit);
    const visible = candidates.slice(window.start, window.end);
    for (let i = 0; i < visible.length; i++) {
      const candidate = visible[i]!;
      const candidateIndex = window.start + i;
      if (!isSelectable(candidate)) {
        const row = makeBox(this.opentui, this.ctx, {
          flexDirection: "column",
          borderStyle: "single",
          border: ["top"],
          borderColor: this.theme.border,
          paddingX: 1,
          backgroundColor: this.theme.surfaceOverlay ?? this.theme.surface,
        });
        row.add?.(
          makeText(this.opentui, this.ctx, {
            content: candidate.label,
            fg: this.theme.textSubtle,
          }),
        );
        this.optionsBox.add?.(row);
        this.rows.push(row);
        continue;
      }
      const selected = candidateIndex === this.selectedIndex;
      const hovered = candidateIndex === this.hoverIndex && !selected;
      const row = makeBox(this.opentui, this.ctx, {
        flexDirection: "row",
        height: 1,
        paddingX: 1,
        backgroundColor: selected ? this.theme.selectionBg : hovered ? this.theme.rowHoverBg : this.theme.surfaceOverlay,
        focusable: true,
        cursor: "pointer",
      });
      addCandidateCells(row, this.opentui, this.ctx, this.theme, candidate, this.trigger, selected, hovered);
      row.onMouseOver = () => {
        if (this.hoverIndex === candidateIndex) return;
        this.setHoverIndex(candidateIndex);
      };
      row.onMouseOut = () => {
        if (this.hoverIndex !== candidateIndex) return;
        this.setHoverIndex(null);
      };
      row.onMouseDown = (event: any) => {
        if (event?.type === "down" && (event.button === 0 || event.button == null)) {
          this.hoverIndex = null;
          this.selectedIndex = candidateIndex;
          this.commit({ index: candidateIndex });
        }
      };
      this.optionsBox.add?.(row);
      this.rows.push(row);
    }
    const overflow = candidates.length - visible.length;
    if (this.commandMode && overflow > 0) {
      const row = makeText(this.opentui, this.ctx, {
        content: `  ${glyphs.dividerDot} ${overflow} more · type to filter`,
        fg: this.theme.textSubtle,
      });
      this.optionsBox.add?.(row);
      this.rows.push(row);
    }
    if (this.hintRow && "content" in this.hintRow) this.hintRow.content = hintLine(this.commandMode || this.trigger === "/" ? "run" : "insert");
  }

  private setOptionsVisible(visible: boolean): void {
    if (!this.optionsBox) return;
    if ("visible" in this.optionsBox) this.optionsBox.visible = visible;
    if ("enableLayout" in this.optionsBox) this.optionsBox.enableLayout = visible;
  }

  private setCollapsedEmptyState(collapsed: boolean): void {
    if (this.header) {
      if ("visible" in this.header) this.header.visible = !collapsed;
      if ("enableLayout" in this.header) this.header.enableLayout = !collapsed;
    }
    if (this.hintWrap) {
      if ("visible" in this.hintWrap) this.hintWrap.visible = !collapsed;
      if ("enableLayout" in this.hintWrap) this.hintWrap.enableLayout = !collapsed;
    }
    if (this.emptyRow) {
      if ("visible" in this.emptyRow) this.emptyRow.visible = collapsed;
      if ("enableLayout" in this.emptyRow) this.emptyRow.enableLayout = collapsed;
    }
    if (this.node && "minHeight" in this.node) this.node.minHeight = collapsed ? 1 : 4;
  }
}

function addCandidateCells(row: any, opentui: any, ctx: any, theme: Theme, candidate: PickerCandidate, trigger: MentionTrigger, selected: boolean, hovered: boolean): void {
  row.add?.(
    makeText(opentui, ctx, {
      content: `${selected ? glyphs.chevron : hovered ? glyphs.hover : " "} `,
      fg: selected ? theme.accent : hovered ? theme.rowHoverFg : theme.textSubtle,
      width: MARKER_WIDTH,
    }),
  );
  if (trigger === "@") {
    addFileCandidateCells(row, opentui, ctx, theme, candidate, selected, hovered);
  } else if (trigger === "/") {
    addCommandCandidateCells(row, opentui, ctx, theme, candidate, selected, hovered);
  } else {
    addSkillCandidateCells(row, opentui, ctx, theme, candidate, selected, hovered);
  }
}

function addCommandCandidateCells(row: any, opentui: any, ctx: any, theme: Theme, candidate: PickerCandidate, selected: boolean, hovered: boolean): void {
  const descWidth = Math.max(0, PICKER_CONTENT_WIDTH - MARKER_WIDTH - LABEL_WIDTH - CUE_WIDTH);
  row.add?.(
    makeText(opentui, ctx, {
      content: fitText(candidate.label, LABEL_WIDTH).padEnd(LABEL_WIDTH),
      fg: labelFg(theme, selected, hovered),
      width: LABEL_WIDTH,
    }),
  );
  row.add?.(
    makeText(opentui, ctx, {
      content: candidate.description ? fitText(candidate.description, descWidth).padEnd(descWidth) : "".padEnd(descWidth),
      fg: detailFg(theme, selected, hovered),
      width: descWidth,
    }),
  );
  row.add?.(
    makeText(opentui, ctx, {
      content: selected ? ` ${glyphs.enterCue}` : "  ",
      fg: selected ? theme.accent : theme.textSubtle,
      width: CUE_WIDTH,
    }),
  );
}

function addFileCandidateCells(row: any, opentui: any, ctx: any, theme: Theme, candidate: PickerCandidate, selected: boolean, hovered: boolean): void {
  const meta = candidate.meta ?? "";
  const metaWidth = meta ? Math.max(4, meta.length) : 0;
  const labelWidth = Math.max(12, PICKER_CONTENT_WIDTH - MARKER_WIDTH - metaWidth);
  row.add?.(
    makeText(opentui, ctx, {
      content: fitText(candidate.label, labelWidth).padEnd(labelWidth),
      fg: labelFg(theme, selected, hovered),
      width: labelWidth,
    }),
  );
  if (meta) {
    row.add?.(
      makeText(opentui, ctx, {
        content: meta.padStart(metaWidth),
        fg: theme.textSubtle,
        width: metaWidth,
      }),
    );
  }
}

function addSkillCandidateCells(row: any, opentui: any, ctx: any, theme: Theme, candidate: PickerCandidate, selected: boolean, hovered: boolean): void {
  const descWidth = Math.max(0, PICKER_CONTENT_WIDTH - MARKER_WIDTH - LABEL_WIDTH);
  const visibleLabel = candidate.label.replace(/^\$/, "");
  row.add?.(
    makeText(opentui, ctx, {
      content: fitText(visibleLabel, LABEL_WIDTH).padEnd(LABEL_WIDTH),
      fg: labelFg(theme, selected, hovered),
      width: LABEL_WIDTH,
    }),
  );
  row.add?.(
    makeText(opentui, ctx, {
      content: candidate.description ? fitText(candidate.description, descWidth).padEnd(descWidth) : "".padEnd(descWidth),
      fg: detailFg(theme, selected, hovered),
      width: descWidth,
    }),
  );
}

function labelFg(theme: Theme, selected: boolean, hovered: boolean): string {
  if (selected) return theme.text;
  if (hovered) return theme.rowHoverFg;
  return theme.textMuted;
}

function detailFg(theme: Theme, selected: boolean, hovered: boolean): string {
  if (selected) return theme.textMuted;
  if (hovered) return theme.textMuted;
  return theme.textSubtle;
}

function hintLine(action: "insert" | "run"): string {
  return `${glyphs.kbdL}↑↓${glyphs.kbdR} move   ${glyphs.kbdL}⏎${glyphs.kbdR} ${action}   ${glyphs.kbdL}esc${glyphs.kbdR} cancel`;
}

function fitText(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, Math.max(0, max - 1))}…`;
}

function preferredCandidateIndex(detection: MentionDetection, candidates: PickerCandidate[]): number {
  if (!selectableCount(candidates)) return 0;
  const needle = detection.query.trim().toLowerCase();
  if (!needle) return firstSelectableIndex(candidates);
  let bestIndex = 0;
  let bestScore = Number.POSITIVE_INFINITY;
  for (let i = 0; i < candidates.length; i++) {
    if (!isSelectable(candidates[i])) continue;
    const score = candidateScore(candidates[i]!, detection.trigger, needle);
    if (score < bestScore) {
      bestScore = score;
      bestIndex = i;
    }
  }
  return Number.isFinite(bestScore) ? bestIndex : firstSelectableIndex(candidates);
}

function candidateScore(candidate: PickerCandidate, trigger: MentionTrigger, needle: string): number {
  const label = candidate.label.replace(/^[/@$]/, "").toLowerCase();
  const description = (candidate.description ?? "").toLowerCase();
  if (label === needle) return 0;
  if (label.startsWith(needle)) return 1;
  if (label.includes(needle)) return 2;
  if (trigger === "@" && label.split("/").pop()?.startsWith(needle)) return 3;
  if (description.includes(needle)) return 4;
  return Number.POSITIVE_INFINITY;
}

function visibleCandidateWindow(total: number, selectedIndex: number, limit: number): { start: number; end: number } {
  const size = Math.min(total, Math.max(1, limit));
  let start = selectedIndex - Math.floor(size / 2);
  start = Math.max(0, Math.min(start, total - size));
  return { start, end: start + size };
}

function isSelectable(candidate: PickerCandidate | undefined): candidate is PickerCandidate {
  return Boolean(candidate && !candidate.disabled);
}

function selectableCount(candidates: PickerCandidate[]): number {
  return candidates.filter(isSelectable).length;
}

function firstSelectableIndex(candidates: PickerCandidate[]): number {
  return Math.max(0, candidates.findIndex(isSelectable));
}

function nextSelectableIndex(candidates: PickerCandidate[], current: number, delta: -1 | 1): number {
  if (!candidates.length) return 0;
  let next = current;
  for (let seen = 0; seen < candidates.length; seen += 1) {
    next = (next + delta + candidates.length) % candidates.length;
    if (isSelectable(candidates[next])) return next;
  }
  return firstSelectableIndex(candidates);
}

function selectedOrdinal(candidates: PickerCandidate[], selectedIndex: number): number {
  let ordinal = 0;
  for (let index = 0; index < candidates.length; index += 1) {
    if (!isSelectable(candidates[index])) continue;
    ordinal += 1;
    if (index === selectedIndex) return ordinal;
  }
  return Math.max(1, ordinal);
}
