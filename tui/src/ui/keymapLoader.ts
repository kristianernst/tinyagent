import { existsSync, readFileSync } from "node:fs";
import { homedir, platform } from "node:os";
import { join } from "node:path";
import type { KeyBinding, KeyContext, KeyAction } from "./keymap";

export function keymapPath(): string {
  const base = process.env.XDG_CONFIG_HOME
    ?? (platform() === "win32" ? join(homedir(), "AppData", "Roaming") : join(homedir(), ".config"));
  return join(base, "tinyagent", "tui.json");
}

type Raw = {
  keymap?: Partial<Record<KeyContext, Record<string, KeyAction | "">>>;
  bindings?: Array<{ context: KeyContext; combo: string; action: KeyAction | "" }>;
};

const KNOWN_CONTEXTS: KeyContext[] = ["global", "composer", "transcript", "palette", "modal", "rail"];

export function loadUserKeymap(): KeyBinding[] {
  const path = keymapPath();
  if (!existsSync(path)) return [];
  try {
    const raw = JSON.parse(readFileSync(path, "utf8")) as Raw;
    return normalize(raw);
  } catch {
    return [];
  }
}

function normalize(raw: Raw): KeyBinding[] {
  const out: KeyBinding[] = [];
  if (raw.bindings) {
    for (const binding of raw.bindings) {
      if (!KNOWN_CONTEXTS.includes(binding.context)) continue;
      if (!binding.combo || !binding.action) continue;
      out.push({ context: binding.context, combo: binding.combo, action: binding.action as KeyAction });
    }
  }
  if (raw.keymap) {
    for (const context of Object.keys(raw.keymap) as KeyContext[]) {
      if (!KNOWN_CONTEXTS.includes(context)) continue;
      const bindings = raw.keymap[context] ?? {};
      for (const [combo, action] of Object.entries(bindings)) {
        if (!action) continue;
        out.push({ context, combo, action: action as KeyAction });
      }
    }
  }
  return out;
}
