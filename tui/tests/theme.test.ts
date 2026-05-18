import { expect, test } from "bun:test";
import { applyLocalCommand, themeCycle } from "../src/commands";
import { emptyState } from "../src/state/reducer";
import { resolveTheme, themeNames, themes } from "../src/ui/theme";

test("resolveTheme returns the named theme or a safe default", () => {
  expect(resolveTheme("tiny-dark").name).toBe("tiny-dark");
  expect(resolveTheme("tiny-light").name).toBe("tiny-light");
  expect(resolveTheme("dracula").name).toBe("dracula");
  expect(resolveTheme("gruvbox").name).toBe("gruvbox");
  expect(resolveTheme(undefined).name).toBe("tiny-dark");
  expect(resolveTheme("nope").name).toBe("tiny-dark");
});

test("themes export contains all named themes", () => {
  for (const name of themeNames) {
    expect(themes[name]?.name).toBe(name);
  }
});

test("theme command cycles through every theme", () => {
  let state = emptyState();
  const seen: string[] = [];
  for (let i = 0; i < themeCycle.length; i += 1) {
    state = applyLocalCommand(state, "theme");
    seen.push(state.ui.theme);
  }
  expect(seen).toEqual([...themeCycle.slice(1), themeCycle[0]]);
});
