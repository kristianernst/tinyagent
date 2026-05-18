import type { Theme } from "../theme";
import { makeBox, makeText, makeTextarea } from "../layout";

export type ComposerSubmit = (value: string) => void;
export type ComposerChange = (value: string, cursor: number) => void;

export class ComposerWidget {
  readonly node: any;
  private input: any;
  private hint: any;
  private history: string[] = [];
  private historyIndex = -1;
  private currentDraft = "";
  private placeholderText: string;
  private changeHandler: ComposerChange | null = null;
  onSubmitWatcher: (() => void) | null = null;

  constructor(
    private opentui: any,
    private ctx: any,
    private theme: Theme,
    placeholder = "Ask, plan, or run a slash command. ↑ history. Enter to send. Shift+Enter for newline.",
  ) {
    this.placeholderText = placeholder;
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "rounded",
      border: true,
      borderColor: theme.border,
      focusedBorderColor: theme.borderFocus,
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
      placeholder,
      backgroundColor: theme.surface,
      textColor: theme.text,
      focusable: true,
      keyBindings,
      onContentChange: () => this.fireChange(),
      onCursorChange: () => this.fireChange(),
    });
    this.hint = makeText(opentui, ctx, {
      content: hintLine(),
      fg: theme.textSubtle,
      flexShrink: 0,
    });
    this.node.add?.(this.input);
    this.node.add?.(this.hint);
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
    this.input?.focus?.();
  }

  blur(): void {
    this.input?.blur?.();
  }

  value(): string {
    if (!this.input) return "";
    if (typeof this.input.plainText === "string") return this.input.plainText;
    if (typeof this.input.value === "string") return this.input.value;
    return "";
  }

  setValue(value: string): void {
    if (!this.input) return;
    if ("value" in this.input) {
      this.input.value = value;
    } else if ("initialValue" in this.input) {
      this.input.initialValue = value;
    }
    this.fireChange();
  }

  setPlaceholder(text: string): void {
    if (this.input && "placeholder" in this.input) this.input.placeholder = text;
    this.placeholderText = text;
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
}

function hintLine(): string {
  return "Enter: send · Shift+Enter: newline · ↑/↓: history · Ctrl+K: palette · Ctrl+C: interrupt";
}
