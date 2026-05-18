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
      get plainText() {
        return captured.plainText;
      }
      get cursorOffset() {
        return captured.cursorOffset;
      }
      constructor(_ctx: any, options: any) {
        captured.options = options;
        this.keyBindings = options.keyBindings;
        this.onContentChange = options.onContentChange;
        this.onCursorChange = options.onCursorChange;
        captured.onContentChange = this.onContentChange;
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

test("pushHistory de-dupes and exposes via historyList", () => {
  const { opentui } = fakeOpentui();
  const composer = new ComposerWidget(opentui, {}, resolveTheme("tiny-dark"));
  composer.pushHistory("one");
  composer.pushHistory("one");
  composer.pushHistory("two");
  expect(composer.historyList()).toEqual(["one", "two"]);
});
