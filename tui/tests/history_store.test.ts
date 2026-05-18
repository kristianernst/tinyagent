import { expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { historyPath, loadComposerHistory, saveComposerHistory } from "../src/ui/historyStore";

test("loadComposerHistory returns [] when the history file is absent", () => {
  const previous = process.env.XDG_DATA_HOME;
  process.env.XDG_DATA_HOME = join(tmpdir(), `tinyagent-hist-empty-${Date.now()}`);
  try {
    expect(loadComposerHistory()).toEqual([]);
  } finally {
    if (previous === undefined) delete process.env.XDG_DATA_HOME;
    else process.env.XDG_DATA_HOME = previous;
  }
});

test("saveComposerHistory persists and reloads", () => {
  const dir = mkdtempSync(join(tmpdir(), "tinyagent-hist-"));
  const previous = process.env.XDG_DATA_HOME;
  process.env.XDG_DATA_HOME = dir;
  try {
    expect(historyPath()).toBe(join(dir, "tinyagent", "composer-history"));
    saveComposerHistory(["first", "second", "third"]);
    expect(loadComposerHistory()).toEqual(["first", "second", "third"]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (previous === undefined) delete process.env.XDG_DATA_HOME;
    else process.env.XDG_DATA_HOME = previous;
  }
});

test("saveComposerHistory caps the file at 500 entries", () => {
  const dir = mkdtempSync(join(tmpdir(), "tinyagent-hist-cap-"));
  const previous = process.env.XDG_DATA_HOME;
  process.env.XDG_DATA_HOME = dir;
  try {
    const large = Array.from({ length: 800 }, (_, i) => `entry-${i}`);
    saveComposerHistory(large);
    const loaded = loadComposerHistory();
    expect(loaded.length).toBe(500);
    expect(loaded[0]).toBe("entry-300");
    expect(loaded[loaded.length - 1]).toBe("entry-799");
  } finally {
    rmSync(dir, { recursive: true, force: true });
    if (previous === undefined) delete process.env.XDG_DATA_HOME;
    else process.env.XDG_DATA_HOME = previous;
  }
});
