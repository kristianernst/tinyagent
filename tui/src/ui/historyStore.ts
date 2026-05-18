import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, platform } from "node:os";
import { dirname, join } from "node:path";

const MAX = 500;

export function historyPath(): string {
  const base = process.env.XDG_DATA_HOME
    ?? (platform() === "win32" ? join(homedir(), "AppData", "Local") : join(homedir(), ".local", "share"));
  return join(base, "tinyagent", "composer-history");
}

export function loadComposerHistory(): string[] {
  const path = historyPath();
  if (!existsSync(path)) return [];
  try {
    return readFileSync(path, "utf8")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .slice(-MAX);
  } catch {
    return [];
  }
}

export function saveComposerHistory(history: string[]): void {
  const path = historyPath();
  try {
    mkdirSync(dirname(path), { recursive: true });
    const trimmed = history.slice(-MAX);
    writeFileSync(path, trimmed.join("\n") + (trimmed.length ? "\n" : ""), "utf8");
  } catch {
    // Best-effort: a failed write does not break the session.
  }
}
