import { existsSync, readdirSync, readFileSync } from "node:fs";
import { homedir, platform } from "node:os";
import { join } from "node:path";
import { themes, type Theme } from "./theme";

const REQUIRED_KEYS: (keyof Theme)[] = [
  "name",
  "background",
  "surface",
  "border",
  "text",
];

export function themesDir(): string {
  const base = process.env.XDG_CONFIG_HOME
    ?? (platform() === "win32" ? join(homedir(), "AppData", "Roaming") : join(homedir(), ".config"));
  return join(base, "tinyagent", "themes");
}

export function loadUserThemes(): Theme[] {
  const dir = themesDir();
  if (!existsSync(dir)) return [];
  const loaded: Theme[] = [];
  for (const file of readdirSync(dir)) {
    if (!file.endsWith(".json")) continue;
    try {
      const raw = readFileSync(join(dir, file), "utf8");
      const parsed = JSON.parse(raw) as Partial<Theme>;
      const merged = mergeWithBase(parsed);
      if (merged) loaded.push(merged);
    } catch {
      // Skip invalid themes silently — keep startup resilient.
    }
  }
  return loaded;
}

export function applyUserThemes(): void {
  for (const theme of loadUserThemes()) {
    themes[theme.name] = theme;
  }
}

function mergeWithBase(partial: Partial<Theme>): Theme | null {
  if (!partial.name) return null;
  for (const key of REQUIRED_KEYS) {
    if (key === "name") continue;
    if (typeof partial[key] !== "string") return null;
  }
  // Inherit any unset keys from the default tiny-dark to keep widgets safe.
  const base = themes["tiny-dark"];
  return { ...base, ...partial, name: partial.name } as Theme;
}
