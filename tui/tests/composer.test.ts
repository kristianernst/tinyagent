// Smoke tests for the composer widget. We use a minimal fake opentui module
// (just enough surface area for the widget constructor) and assert that:
//   1. Enter is rebound to submit, and Shift+Enter inserts newline.
//   2. value() reads plainText (the TextareaRenderable property), not value.
//   3. onContentChange fires the registered change handler.
//   4. Pushed history persists in historyList().

import { expect, test } from "bun:test";
import { ComposerWidget } from "../src/ui/widgets/Composer";
import { resolveTheme } from "../src/ui/theme";

type Captured = {
  options: any;
  plainText: string;
  cursorOffset: number;
  onContentChange?: () => void;
  onSubmit?: () => void;
};

function fakeOpentui(): { opentui: any; captured: Captured } {
  const captured: Captured = { options: null, plainText: "", cursorOffset: 0 };
  const opentui = {
    defaultTextareaKeyBindings: [
      { name: "return", action: "newline" },
      { name: "left", action: "move-left" },
    ],
    BoxRenderable: class {
      children: any[] = [];
      visible = true;
      onMouseDown?: (e: any) => void;
      constructor(public _ctx: any, public _opts: any) {}
      get title() {
        return this._opts.title;
      }
      set title(value: string | undefined) {
        this._opts.title = value;
      }
      add(child: any) {
        this.children.push(child);
      }
      remove() {}
      focus() {}
      blur() {}
      on() {}
    },
    TextRenderable: class {
      constructor(public _ctx: any, public _opts: any) {}
      add() {}
      remove() {}
      focus() {}
      blur() {}
      on() {}
      get content() {
        return this._opts.content;
      }
      set content(v: string) {
        this._opts.content = v;
      }
    },
    TextareaRenderable: class {
      keyBindings: any[];
      onContentChange?: () => void;
      onCursorChange?: () => void;
      onSubmit?: () => void;
      placeholder = "";
      get plainText() {
        return captured.plainText;
      }
      get cursorOffset() {
        return captured.cursorOffset;
      }
      set cursorOffset(value: number) {
        captured.cursorOffset = value;
      }
      constructor(_ctx: any, options: any) {
        captured.options = options;
        this.keyBindings = options.keyBindings;
        this.placeholder = options.placeholder;
        this.onContentChange = options.onContentChange;
        this.onCursorChange = options.onCursorChange;
        captured.onContentChange = this.onContentChange;
      }
      setText(value: string) {
        captured.plainText = value;
      }
      focus() {}
      blur() {}
      on() {}
    },
  };
  return { opentui, captured };
}

test("composer overrides Enter to submit and keeps Shift+Enter as newline", () => {
  const { opentui, captured } = fakeOpentui();
  new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  const bindings = captured.options.keyBindings as Array<Record<string, unknown>>;
  // Defaults are preserved as a base
  expect(bindings.some((b) => b.name === "left" && b.action === "move-left")).toBe(true);
  // Last write for plain Enter is submit
  const enterBindings = bindings.filter((b) => b.name === "return" && !b.shift);
  expect(enterBindings.at(-1)?.action).toBe("submit");
  // Shift+Enter is mapped to newline
  expect(bindings.some((b) => b.name === "return" && b.shift && b.action === "newline")).toBe(true);
});

test("composer reads value from plainText (Textarea has no `value` getter)", () => {
  const { opentui, captured } = fakeOpentui();
  const composer = new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  captured.plainText = "hello";
  captured.cursorOffset = 5;
  expect(composer.value()).toBe("hello");
  expect(composer.cursor()).toBe(5);
});

test("composer fires onChange whenever onContentChange triggers", () => {
  const { opentui, captured } = fakeOpentui();
  const composer = new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  const seen: Array<{ value: string; cursor: number }> = [];
  composer.setOnChange((value, cursor) => seen.push({ value, cursor }));
  captured.plainText = "/he";
  captured.cursorOffset = 3;
  captured.onContentChange?.();
  expect(seen.at(-1)).toEqual({ value: "/he", cursor: 3 });
});

test("composer uses Paper cursor and selection tokens", () => {
  const { opentui, captured } = fakeOpentui();
  const theme = resolveTheme("paper-dark");
  new ComposerWidget(opentui, {}, theme);

  expect(captured.options.showCursor).toBe(true);
  expect(captured.options.cursorColor).toBe(theme.cursorBg);
  expect(captured.options.cursorStyle).toEqual({ style: "block", blinking: true });
  expect(captured.options.selectionBg).toBe(theme.selectionBg);
  expect(captured.options.selectionFg).toBe(theme.selectionFg);
  expect(captured.options.placeholderColor).toBe(theme.textSubtle);
  expect(captured.options.focusedBackgroundColor).toBe(theme.surface);
  expect(captured.options.focusedTextColor).toBe(theme.text);
});

test("pushHistory de-dupes and exposes via historyList", () => {
  const { opentui } = fakeOpentui();
  const composer = new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  composer.pushHistory("one");
  composer.pushHistory("one");
  composer.pushHistory("two");
  expect(composer.historyList()).toEqual(["one", "two"]);
});

test("composer hint chips dispatch real mouse hits", () => {
  const { opentui } = fakeOpentui();
  const composer = new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  const seen: string[] = [];
  composer.setOnHintAction((action) => seen.push(action));
  const hint = (composer as any).hint;

  for (const label of ["commands", "files", "skills"]) {
    const x = hint.content.indexOf(label);
    expect(x).toBeGreaterThan(-1);
    hint.onMouseDown({ type: "down", button: 0, x });
  }

  expect(hint.content).toContain("⌜esc⌟ cancel turn");
  expect(hint.content).not.toContain("history");
  expect(seen).toEqual(["/", "@", "$"]);
});

test("composer inserts hint triggers at the active draft tail", () => {
  const { opentui, captured } = fakeOpentui();
  const composer = new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  const seen: Array<{ value: string; cursor: number }> = [];
  captured.plainText = "summarize";
  captured.cursorOffset = "summarize".length;
  composer.setOnChange((value, cursor) => seen.push({ value, cursor }));

  composer.insertTrigger("@");

  expect(captured.plainText).toBe("summarize @");
  expect(seen.at(-1)).toEqual({ value: "summarize @", cursor: "summarize @".length });
});

test("composer hint chip hover paints the shared gutter glyph without resizing", () => {
  const { opentui } = fakeOpentui();
  const composer = new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  composer.setViewportWidth(120);
  const hint = (composer as any).hint;
  const initialLength = hint.content.length;

  hint.onMouseMove({ type: "move", x: hint.content.indexOf("skills") });

  expect(hint.content).toContain("▸⌜$⌟ skills");
  expect(hint.content.length).toBe(initialLength);

  hint.onMouseOut();
  expect(hint.content).toContain(" ⌜$⌟ skills");
  expect(hint.content.length).toBe(initialLength);
});

test("composer hint keeps escape action in a right lane", () => {
  const { opentui } = fakeOpentui();
  const composer = new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  composer.setViewportWidth(120);
  const hint = (composer as any).hint;

  expect(hint.content).toContain("⌜enter⌟ send");
  expect(hint.content).toContain("⌜⇧enter⌟ newline");
  expect(hint.content).not.toContain("⌜⏎⌟ send");
  expect(hint.content.indexOf("⌜esc⌟ cancel turn")).toBeGreaterThan(hint.content.indexOf("⌜$⌟ skills") + 20);

  composer.setViewportWidth(80);
  expect(hint.content).toContain("⌜⏎⌟ send");
  expect(hint.content.indexOf("⌜esc⌟ cancel turn")).toBeGreaterThan(hint.content.indexOf("⌜$⌟ skills"));
});

test("composer density switches at the Paper 100-column threshold", () => {
  const { opentui } = fakeOpentui();
  const composer = new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  const hint = (composer as any).hint;

  composer.setViewportWidth(99);
  expect(hint.content).toContain("⌜⏎⌟ send");
  expect(hint.content).toContain("⌜/⌟ cmds");

  composer.setViewportWidth(100);
  expect(hint.content).toContain("⌜enter⌟ send");
  expect(hint.content).toContain("⌜/⌟ commands");
});

test("composer focus state keeps the unfocused input quiet", () => {
  const { opentui } = fakeOpentui();
  const composer = new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  const card = (composer as any).card;
  const input = (composer as any).input;

  expect(card.title).toBeUndefined();
  expect(input.placeholder).toBe("");

  composer.focus();
  expect(card.title).toBeUndefined();
  expect(input.placeholder).toBe("ask, plan, or /command");

  composer.blur();
  expect(card.title).toBeUndefined();
  expect(input.placeholder).toBe("");
});
