import { expect, test } from "bun:test";
import { applyLocalCommand, themeCycle } from "../src/commands";
import { emptyState } from "../src/state/reducer";
import { resolveTheme, selectableThemeNames, themeNames, themes } from "../src/ui/theme";

test("resolveTheme returns the named theme or a safe default", () => {
  expect(resolveTheme("paper-dark").name).toBe("paper-dark");
  expect(resolveTheme("paper-light").name).toBe("paper-light");
  expect(resolveTheme("mono").name).toBe("mono");
  expect(resolveTheme("high-contrast").name).toBe("high-contrast");
  expect(resolveTheme(undefined).name).toBe("paper-dark");
  expect(resolveTheme("nope").name).toBe("paper-dark");
});

test("legacy theme names resolve for back-compat", () => {
  // Old configs persisted tiny-dark / tiny-light / dracula / gruvbox before the
  // token system rewrite. Those names must still load.
  expect(resolveTheme("tiny-dark").name).toBe("tiny-dark");
  expect(resolveTheme("tiny-light").name).toBe("tiny-light");
  expect(resolveTheme("dracula").name).toBe("dracula");
  expect(resolveTheme("gruvbox").name).toBe("gruvbox");
});

test("themes export contains all named themes", () => {
  for (const name of selectableThemeNames) {
    expect(themes[name]?.name).toBe(name);
  }
});

test("high contrast is opt-in and not part of the quick cycle", () => {
  expect(selectableThemeNames).toEqual(["paper-dark", "paper-light", "mono", "high-contrast"]);
  expect(themeNames).toEqual(["paper-dark", "paper-light", "mono"]);
  expect(themeCycle).toEqual(themeNames);
});

test("theme command cycles through every default theme", () => {
  let state = emptyState();
  const seen: string[] = [];
  for (let i = 0; i < themeCycle.length; i += 1) {
    state = applyLocalCommand(state, "theme");
    seen.push(state.ui.theme);
  }
  expect(seen).toEqual([...themeCycle.slice(1), themeCycle[0]]);
});
