import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { applyUserThemes, loadUserThemes, themesDir } from "../src/ui/themeLoader";
import { themes } from "../src/ui/theme";

test("loadUserThemes returns [] when the themes directory is missing", () => {
  const previous = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = join(tmpdir(), `tinyagent-${Date.now()}-empty`);
  try {
    expect(loadUserThemes()).toEqual([]);
  } finally {
    if (previous === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previous;
  }
});

test("loadUserThemes merges with tiny-dark defaults and registers via applyUserThemes", () => {
  const dir = mkdtempSync(join(tmpdir(), "tinyagent-theme-"));
  const previous = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = dir;
  try {
    const target = join(dir, "tinyagent", "themes");
    mkdirSync(target, { recursive: true });
    writeFileSync(
      join(target, "neon.json"),
      JSON.stringify({
        name: "neon",
        background: "#000000",
        surface: "#111111",
        border: "#22ff22",
        text: "#22ffff",
      }),
    );
    expect(themesDir()).toBe(target);
    const loaded = loadUserThemes();
    expect(loaded.length).toBe(1);
    expect(loaded[0]?.name).toBe("neon");
    expect(loaded[0]?.surface).toBe("#111111");
    expect(loaded[0]?.accent).toBe(themes["tiny-dark"].accent);
    applyUserThemes();
    expect(themes["neon"]?.name).toBe("neon");
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (previous === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previous;
    delete themes["neon"];
  }
});

test("invalid theme JSON is skipped silently", () => {
  const dir = mkdtempSync(join(tmpdir(), "tinyagent-theme-bad-"));
  const previous = process.env.XDG_CONFIG_HOME;
  process.env.XDG_CONFIG_HOME = dir;
  try {
    const target = join(dir, "tinyagent", "themes");
    mkdirSync(target, { recursive: true });
    writeFileSync(join(target, "bad.json"), "{ not json");
    writeFileSync(join(target, "missing-name.json"), JSON.stringify({ background: "#000" }));
    expect(loadUserThemes()).toEqual([]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (previous === undefined) delete process.env.XDG_CONFIG_HOME;
    else process.env.XDG_CONFIG_HOME = previous;
  }
});
