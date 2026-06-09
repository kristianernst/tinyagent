import { expect, test } from "bun:test";
import { comboFromKeyEvent, defaultKeymap, loadKeymap, lookupAction } from "../src/ui/keymap";

test("comboFromKeyEvent renders canonical chords", () => {
  expect(comboFromKeyEvent({ name: "k", ctrl: true })).toBe("Ctrl+k");
  expect(comboFromKeyEvent({ name: "return" })).toBe("Enter");
  expect(comboFromKeyEvent({ name: "tab", shift: true })).toBe("Shift+Tab");
  expect(comboFromKeyEvent({ name: "up" })).toBe("Up");
  expect(comboFromKeyEvent({ name: "pageup" })).toBe("PageUp");
});

test("lookupAction falls back to global context", () => {
  expect(lookupAction(defaultKeymap, "composer", "Ctrl+K")).toBe("open-palette");
  expect(lookupAction(defaultKeymap, "transcript", "Ctrl+K")).toBe("open-palette");
  expect(lookupAction(defaultKeymap, "transcript", "Ctrl+R")).toBe("history-search");
  expect(lookupAction(defaultKeymap, "transcript", "Ctrl+B")).toBe("toggle-rail");
});

test("composer bindings override global Up", () => {
  expect(lookupAction(defaultKeymap, "composer", "Up")).toBe("history-prev");
  expect(lookupAction(defaultKeymap, "transcript", "Up")).toBe("scroll-up");
});

test("loadKeymap merges custom bindings ahead of defaults", () => {
  const custom = [{ context: "global" as const, combo: "Ctrl+K", action: "toggle-rail" as const }];
  const merged = loadKeymap(custom);
  expect(lookupAction(merged, "global", "Ctrl+K")).toBe("toggle-rail");
});
