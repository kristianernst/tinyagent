import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { keymapPath, loadUserKeymap } from "../src/ui/keymapLoader";

test("loadUserKeymap returns [] when tui.json is missing", () => {
  const previous = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = join(tmpdir(), `tinyagent-keymap-empty-${Date.now()}`);
  try {
    expect(loadUserKeymap()).toEqual([]);
  } finally {
    if (previous === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previous;
  }
});

test("loadUserKeymap parses both bindings[] and keymap{} forms", () => {
  const dir = mkdtempSync(join(tmpdir(), "tinyagent-keymap-"));
  const previous = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = dir;
  try {
    mkdirSync(join(dir, "tinyagent"), { recursive: true });
    writeFileSync(
      join(dir, "tinyagent", "tui.json"),
      JSON.stringify({
        bindings: [
          { context: "global", combo: "Ctrl+J", action: "open-palette" },
          { context: "made-up", combo: "Ctrl+L", action: "open-palette" },
        ],
        keymap: {
          composer: { "Alt+Enter": "newline" },
        },
      }),
    );
    expect(keymapPath()).toBe(join(dir, "tinyagent", "tui.json"));
    const bindings = loadUserKeymap();
    expect(bindings.find((b) => b.combo === "Ctrl+J")?.action).toBe("open-palette");
    expect(bindings.find((b) => b.combo === "Alt+Enter")?.context).toBe("composer");
    expect(bindings.find((b) => b.combo === "Ctrl+L")).toBeUndefined();
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (previous === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previous;
  }
});

test("loadUserKeymap tolerates malformed JSON", () => {
  const dir = mkdtempSync(join(tmpdir(), "tinyagent-keymap-bad-"));
  const previous = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = dir;
  try {
    mkdirSync(join(dir, "tinyagent"), { recursive: true });
    writeFileSync(join(dir, "tinyagent", "tui.json"), "{ broken");
    expect(loadUserKeymap()).toEqual([]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (previous === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previous;
  }
});
