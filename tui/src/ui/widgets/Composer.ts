import { glyphs } from "../../design/glyphs";
import type { MentionTrigger } from "../../state/reducer";
import type { Theme } from "../theme";
import { isCompactViewport, makeBox, makeText, makeTextarea } from "../layout";

export type ComposerSubmit = (value: string) => void;
export type ComposerChange = (value: string, cursor: number) => void;
export type ComposerHintAction = MentionTrigger | "history";

type HintSegment = {
  start: number;
  end: number;
  action: ComposerHintAction;
};

export class ComposerWidget {
  readonly node: any;
  private card: any;
  private input: any;
  private hint: any;
  private history: string[] = [];
  private historyIndex = -1;
  private currentDraft = "";
  private placeholderText: string;
  private focused = false;
  private changeHandler: ComposerChange | null = null;
  private hintActionHandler: ((action: ComposerHintAction) => void) | null = null;
  private hintSegments: HintSegment[] = [];
  private compactHintLine = false;
  private hoveredHintAction: ComposerHintAction | null = null;
  private viewportWidth = 120;
  onSubmitWatcher: (() => void) | null = null;

  constructor(
    private opentui: any,
    private ctx: any,
    private theme: Theme,
    placeholder = "ask, plan, or /command",
  ) {
    this.placeholderText = placeholder;

    // Outer wrapper keeps the hint row pinned below the bordered card.
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      flexShrink: 0,
      marginX: 2,
      marginBottom: 1,
    });

    // The bordered card itself. Per DESIGN_TOKENS.md §4.3 the focus signal is
    // *border weight* — color stays `border.subtle` when unfocused and shifts
    // to `border.focus` (brand) only while the composer holds focus.
    this.card = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "rounded",
      border: true,
      borderColor: theme.border,
      focusedBorderColor: theme.borderFocus,
      title: undefined,
      paddingX: 1,
      paddingY: 0,
      backgroundColor: theme.surface,
      flexShrink: 0,
    });

    // Override Textarea bindings: Enter submits, Shift+Enter inserts a newline.
    const keyBindings = this.buildKeyBindings();

    this.input = makeTextarea(opentui, ctx, {
      minHeight: 1,
      maxHeight: 8,
      placeholder: "",
      placeholderColor: theme.textSubtle,
      backgroundColor: theme.surface,
      textColor: theme.text,
      focusedBackgroundColor: theme.surface,
      focusedTextColor: theme.text,
      selectionBg: theme.selectionBg,
      selectionFg: theme.selectionFg,
      showCursor: true,
      cursorColor: theme.cursorBg,
      cursorStyle: { style: "block", blinking: true },
      focusable: true,
      keyBindings,
      onContentChange: () => this.fireChange(),
      onCursorChange: () => this.fireChange(),
    });
    this.card.add?.(this.input);

    this.hint = makeText(opentui, ctx, {
      content: "",
      fg: theme.textSubtle,
      flexShrink: 0,
      marginTop: 0,
      cursor: "pointer",
    });
    this.hint.onMouseDown = (event: any) => this.handleHintMouseDown(event);
    this.hint.onMouseMove = (event: any) => this.handleHintHover(event);
    this.hint.onMouseOver = (event: any) => this.handleHintHover(event);
    this.hint.onMouseOut = () => this.setHoveredHintAction(null);
    this.applyHintLine(false);

    this.applyFocusState();
    this.node.add?.(this.card);
    this.node.add?.(this.hint);
  }

  setViewportWidth(width: number): void {
    if (!this.hint || this.hint.content === undefined) return;
    this.viewportWidth = width;
    this.applyHintLine(isCompactViewport(width));
  }

  setOnHintAction(handler: (action: ComposerHintAction) => void): void {
    this.hintActionHandler = handler;
  }

  activateHint(action: ComposerHintAction): void {
    this.hintActionHandler?.(action);
  }

  setHoveredHintAction(action: ComposerHintAction | null): void {
    if (this.hoveredHintAction === action) return;
    this.hoveredHintAction = action;
    this.applyHintLine(this.compactHintLine);
  }

  insertTrigger(trigger: MentionTrigger): void {
    const base = this.value().replace(/\s+$/g, "");
    this.setValue(base ? `${base} ${trigger}` : trigger);
    this.focus();
  }

  private buildKeyBindings(): unknown[] | undefined {
    if (!this.opentui) return undefined;
    const defaults = (this.opentui as any).defaultTextareaKeyBindings;
    if (!defaults) return undefined;
    // Defaults already include `{ name: "return", action: "newline" }`. Push
    // our overrides afterwards — Textarea's key map keeps the last write per
    // key, so submit wins for plain Enter and newline still triggers on Shift+Enter.
    return [
      ...defaults,
      { name: "return", action: "submit" },
      { name: "return", shift: true, action: "newline" },
    ];
  }

  setOnSubmit(handler: ComposerSubmit): void {
    if (!this.input) return;
    const wrapped = () => {
      const value = this.value().trim();
      if (!value) return;
      this.pushHistory(value);
      this.onSubmitWatcher?.();
      handler(value);
      this.clear();
    };
    if ("onSubmit" in this.input) {
      this.input.onSubmit = wrapped;
    } else if (typeof this.input.on === "function") {
      this.input.on("enter", wrapped);
    }
  }

  historyList(): string[] {
    return this.history.slice();
  }

  setOnChange(handler: ComposerChange): void {
    this.changeHandler = handler;
    // Fire once with the current state so subscribers can hydrate.
    this.fireChange();
  }

  private fireChange(): void {
    if (!this.changeHandler) return;
    const value = this.value();
    const cursor = this.cursor();
    this.changeHandler(value, cursor);
  }

  cursor(): number {
    if (!this.input) return 0;
    if (typeof this.input.cursorOffset === "number") return this.input.cursorOffset;
    if (typeof this.input.cursorCharacterOffset === "number") return this.input.cursorCharacterOffset;
    return this.value().length;
  }

  focus(): void {
    this.focused = true;
    this.applyFocusState();
    this.input?.focus?.();
  }

  blur(): void {
    this.input?.blur?.();
    this.focused = false;
    this.applyFocusState();
  }

  value(): string {
    if (!this.input) return "";
    if (typeof this.input.plainText === "string") return this.input.plainText;
    if (typeof this.input.value === "string") return this.input.value;
    return "";
  }

  setValue(value: string): void {
    if (!this.input) return;
    // EditBufferRenderable exposes `setText(text)` (preferred) and an
    // `initialValue` setter as fallback for stripped builds. We try both so
    // the composer behaves the same in tests and in the live shell.
    if (typeof this.input.setText === "function") {
      this.input.setText(value);
    } else if ("initialValue" in this.input) {
      this.input.initialValue = value;
    } else if ("value" in this.input) {
      this.input.value = value;
    }
    // After replacing text, place the cursor at the end so mention detection
    // (which looks backwards from the cursor) finds the trigger we just typed.
    if ("cursorOffset" in this.input) {
      try {
        this.input.cursorOffset = value.length;
      } catch {
        /* renderer may reject mid-frame writes; tolerate. */
      }
    }
    this.fireChange();
  }

  setPlaceholder(text: string): void {
    this.placeholderText = text;
    this.applyFocusState();
  }

  clear(): void {
    this.setValue("");
    this.historyIndex = -1;
    this.currentDraft = "";
  }

  pushHistory(value: string): void {
    if (!value) return;
    if (this.history[this.history.length - 1] === value) return;
    this.history.push(value);
    if (this.history.length > 200) this.history.shift();
    this.historyIndex = -1;
  }

  historyPrev(): void {
    if (!this.history.length) return;
    if (this.historyIndex === -1) this.currentDraft = this.value();
    this.historyIndex = Math.min(this.history.length - 1, this.historyIndex + 1);
    const slot = this.history.length - 1 - this.historyIndex;
    this.setValue(this.history[slot]);
  }

  historyNext(): void {
    if (!this.history.length) {
      this.setValue(this.currentDraft);
      return;
    }
    if (this.historyIndex <= 0) {
      this.historyIndex = -1;
      this.setValue(this.currentDraft);
      return;
    }
    this.historyIndex -= 1;
    const slot = this.history.length - 1 - this.historyIndex;
    this.setValue(this.history[slot]);
  }

  private applyHintLine(compact: boolean): void {
    this.compactHintLine = compact;
    const next = hintLine(compact, this.hoveredHintAction, this.viewportWidth);
    this.hintSegments = next.segments;
    if (this.hint && "content" in this.hint && this.hint.content !== next.content) {
      this.hint.content = next.content;
    }
  }

  private applyFocusState(): void {
    if (this.card && "title" in this.card) {
      this.card.title = undefined;
    }
    if (this.input && "placeholder" in this.input) {
      this.input.placeholder = this.focused ? this.placeholderText : "";
    }
  }

  private handleHintMouseDown(event: any): void {
    if (!isPrimaryDown(event)) return;
    const offset = textOffset(event, this.hint);
    const segment = this.hintSegments.find((item) => offset >= item.start && offset < item.end);
    if (segment) this.activateHint(segment.action);
  }

  private handleHintHover(event: any): void {
    const offset = textOffset(event, this.hint);
    const segment = this.hintSegments.find((item) => offset >= item.start && offset < item.end);
    this.setHoveredHintAction(segment?.action ?? null);
  }
}

function hintLine(compact: boolean, hovered: ComposerHintAction | null, viewportWidth: number): { content: string; segments: HintSegment[] } {
  const k = (s: string) => `${glyphs.kbdL}${s}${glyphs.kbdR}`;
  const segments: HintSegment[] = [];
  let left = "";
  const append = (value: string, action?: ComposerHintAction) => {
    const start = left.length;
    left += value;
    if (action) segments.push({ start, end: left.length, action });
  };
  const gap = () => append("  ");
  const action = (key: string, label: string, hintAction: ComposerHintAction, markerLane = true) =>
    markerLane ? `${hovered === hintAction ? glyphs.hover : " "}${k(key)} ${label}` : `${k(key)}${hovered === hintAction ? glyphs.hover : " "}${label}`;
  const right = `${k("esc")} cancel turn`;

  if (compact) {
    append(`${k("⏎")} send`);
    gap();
    append(`${k("⇧⏎")} newline`);
    gap();
    append(action("/", "cmds", "/", false), "/");
    gap();
    append(action("@", "files", "@", false), "@");
    gap();
    append(action("$", "skills", "$", false), "$");
    return { content: withRightHint(left, right, viewportWidth), segments };
  }
  append(`${k("enter")} send`);
  gap();
  append(`${k("⇧enter")} newline`);
  gap();
  append(action("/", "commands", "/"), "/");
  gap();
  append(action("@", "files", "@"), "@");
  gap();
  append(action("$", "skills", "$"), "$");
  return { content: withRightHint(left, right, viewportWidth), segments };
}

function withRightHint(left: string, right: string, viewportWidth: number): string {
  const width = Math.max(0, Math.floor(viewportWidth) - 4);
  if (!width || left.length + right.length + 2 >= width) return `${left}  ${right}`;
  return `${left}${" ".repeat(width - left.length - right.length)}${right}`;
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
