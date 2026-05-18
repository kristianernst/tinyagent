import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { SettingsState } from "../../state/reducer";
import type { Theme } from "../theme";
import { keymapPath } from "../keymapLoader";
import { makeBox, makeText } from "../layout";
import { themeNames } from "../theme";

const SPINNERS = ["ascii", "dots", "braille", "scanline", "minimal"];
const TOGGLES = ["off", "on"] as const;

type Row = {
  key: keyof SettingsState;
  label: string;
  options: string[];
};

const ROWS: Row[] = [
  { key: "theme", label: "Theme", options: [...themeNames] },
  { key: "spinner", label: "Spinner", options: SPINNERS },
  { key: "showReasoning", label: "Show reasoning", options: [...TOGGLES] },
  { key: "diffView", label: "Diff view", options: ["unified", "split"] },
  { key: "mouseCapture", label: "Mouse capture", options: [...TOGGLES] },
  { key: "rightRail", label: "Right rail", options: [...TOGGLES] },
];

export type SettingsApply = (next: SettingsState) => void;

export class SettingsWidget {
  readonly node: any;
  private rows = new Map<keyof SettingsState, { node: any; label: any; value: any }>();
  private status: any;
  private hint: any;
  private current: SettingsState;
  private applyHandler: SettingsApply | null = null;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      flexGrow: 1,
      paddingY: 0,
    });
    const header = makeText(opentui, ctx, {
      content: "Settings",
      fg: theme.accent,
    });
    this.node.add?.(header);
    this.current = {
      theme: "tiny-dark",
      spinner: "ascii",
      showReasoning: false,
      diffView: "unified",
      mouseCapture: true,
      rightRail: true,
      dirty: false,
    };
    for (const row of ROWS) {
      const wrap = makeBox(opentui, ctx, {
        flexDirection: "row",
        marginTop: 1,
        paddingX: 1,
        borderStyle: "single",
        border: ["bottom"],
        borderColor: theme.border,
      });
      const label = makeText(opentui, ctx, { content: row.label, fg: theme.textMuted, width: 20 });
      const value = makeText(opentui, ctx, { content: this.valueFor(row.key, this.current), fg: theme.text });
      wrap.add?.(label);
      wrap.add?.(value);
      this.rows.set(row.key, { node: wrap, label, value });
      this.node.add?.(wrap);
    }
    this.status = makeText(opentui, ctx, {
      content: "/settings set <key> <value> · /settings save · /settings reset",
      fg: theme.textSubtle,
      marginTop: 1,
    });
    this.hint = makeText(opentui, ctx, {
      content: "",
      fg: theme.warning,
      marginTop: 1,
    });
    this.node.add?.(this.status);
    this.node.add?.(this.hint);
  }

  update(settings: SettingsState): void {
    this.current = settings;
    for (const [key, refs] of this.rows) {
      if (refs.value && refs.value.content !== undefined) {
        refs.value.content = this.valueFor(key, settings);
      }
    }
    if (this.hint && this.hint.content !== undefined) {
      this.hint.content = settings.dirty ? "Unsaved changes — run /settings save to persist." : "";
    }
  }

  bindApply(handler: SettingsApply): void {
    this.applyHandler = handler;
  }

  setValue(key: keyof SettingsState, value: string): SettingsState {
    const next = { ...this.current, dirty: true };
    if (key === "showReasoning" || key === "mouseCapture" || key === "rightRail") {
      next[key] = value === "on" || value === "true" || value === "1";
    } else if (key === "diffView") {
      next.diffView = value === "split" ? "split" : "unified";
    } else if (key === "theme" || key === "spinner") {
      next[key] = value;
    } else {
      return this.current;
    }
    this.applyHandler?.(next);
    return next;
  }

  private valueFor(key: keyof SettingsState, settings: SettingsState): string {
    const value = settings[key];
    if (typeof value === "boolean") return value ? "on" : "off";
    return String(value);
  }
}

/**
 * Persist a settings snapshot to ~/.config/tinyagent/tui.json.
 * Existing keys outside `settings` are preserved.
 */
export function saveSettings(settings: SettingsState): boolean {
  const path = keymapPath();
  try {
    let raw: Record<string, any> = {};
    if (existsSync(path)) {
      try {
        raw = JSON.parse(readFileSync(path, "utf8")) as Record<string, any>;
      } catch {
        raw = {};
      }
    }
    raw.settings = {
      theme: settings.theme,
      spinner: settings.spinner,
      showReasoning: settings.showReasoning,
      diffView: settings.diffView,
      mouseCapture: settings.mouseCapture,
      rightRail: settings.rightRail,
    };
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify(raw, null, 2));
    return true;
  } catch {
    return false;
  }
}

export function loadSettings(): Partial<SettingsState> {
  const path = keymapPath();
  if (!existsSync(path)) return {};
  try {
    const raw = JSON.parse(readFileSync(path, "utf8")) as Record<string, any>;
    return (raw.settings ?? {}) as Partial<SettingsState>;
  } catch {
    return {};
  }
}
