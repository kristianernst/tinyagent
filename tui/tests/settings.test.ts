import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runSettingsCommand } from "../src/controller/settings";
import { emptyState } from "../src/state/reducer";
import { Store } from "../src/state/store";
import { loadSettings, saveSettings } from "../src/ui/widgets/SettingsWidget";

test("/settings set updates state and marks dirty", () => {
  const store = new Store(emptyState());
  runSettingsCommand(store, ["set", "theme", "dracula"]);
  expect(store.get().settings.theme).toBe("dracula");
  expect(store.get().settings.dirty).toBe(true);
});

test("/settings set rejects unknown keys", () => {
  const store = new Store(emptyState());
  const ok = runSettingsCommand(store, ["set", "missing", "value"]);
  expect(ok).toBe(false);
  expect(store.get().errors.some((e) => e.includes("missing"))).toBe(true);
});

test("/settings reset clears to defaults but stays dirty until save", () => {
  const store = new Store({ ...emptyState(), settings: { ...emptyState().settings, theme: "dracula" } });
  runSettingsCommand(store, ["reset"]);
  expect(store.get().settings.theme).toBe("paper-dark");
  expect(store.get().settings.rightRail).toBe(false);
  expect(store.get().settings.dirty).toBe(true);
});

test("/settings rail stays disabled for the Paper shell", () => {
  const store = new Store(emptyState());
  runSettingsCommand(store, ["set", "rail", "on"]);
  expect(store.get().settings.rightRail).toBe(false);
  expect(store.get().settings.dirty).toBe(true);
});

test("/settings spinner accepts only the Paper braille primitive", () => {
  const store = new Store(emptyState());
  runSettingsCommand(store, ["set", "spinner", "dots"]);
  expect(store.get().settings.spinner).toBe("braille");
  expect(store.get().settings.dirty).toBe(true);
});

test("saveSettings writes JSON and loadSettings reads it back", () => {
  const dir = mkdtempSync(join(tmpdir(), "tinyagent-set-"));
  const previous = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = dir;
  try {
    const snap = { ...emptyState().settings, theme: "gruvbox", mouseCapture: false };
    expect(saveSettings(snap)).toBe(true);
    const raw = JSON.parse(readFileSync(join(dir, "tinyagent", "tui.json"), "utf8"));
    expect(raw.settings.theme).toBe("gruvbox");
    expect(loadSettings().theme).toBe("gruvbox");
    expect(loadSettings().mouseCapture).toBe(false);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (previous === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previous;
  }
});

test("loadSettings normalizes removed spinner names", () => {
  const dir = mkdtempSync(join(tmpdir(), "tinyagent-set-spinner-"));
  const previous = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = dir;
  try {
    mkdirSync(join(dir, "tinyagent"), { recursive: true });
    writeFileSync(join(dir, "tinyagent", "tui.json"), JSON.stringify({ settings: { spinner: "scanline" } }));
    expect(loadSettings().spinner).toBe("braille");
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (previous === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previous;
  }
});

test("saveSettings preserves unrelated keys in tui.json", () => {
  const dir = mkdtempSync(join(tmpdir(), "tinyagent-set-preserve-"));
  const previous = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = dir;
  try {
    mkdirSync(join(dir, "tinyagent"), { recursive: true });
    writeFileSync(
      join(dir, "tinyagent", "tui.json"),
      JSON.stringify({ bindings: [{ context: "global", combo: "Ctrl+J", action: "open-palette" }] }),
    );
    saveSettings({ ...emptyState().settings, theme: "dracula" });
    const raw = JSON.parse(readFileSync(join(dir, "tinyagent", "tui.json"), "utf8"));
    expect(raw.bindings?.length).toBe(1);
    expect(raw.settings.theme).toBe("dracula");
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (previous === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previous;
  }
});
