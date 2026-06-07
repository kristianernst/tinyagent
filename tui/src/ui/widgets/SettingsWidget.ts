import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import type { SettingsState } from "../../state/reducer";
import type { Theme } from "../theme";
import { keymapPath } from "../keymapLoader";
import { selectableThemeNames } from "../theme";
import { InfoPanelWidget, type InfoPanelContent } from "./InfoPanelWidget";

const SPINNERS = ["braille"];
const TOGGLES = ["off", "on"] as const;

type Row = {
  key: keyof SettingsState;
  label: string;
  options: string[];
};

const ROWS: Row[] = [
  { key: "theme", label: "Theme", options: [...selectableThemeNames] },
  { key: "spinner", label: "Spinner", options: SPINNERS },
  { key: "showReasoning", label: "Reasoning", options: [...TOGGLES] },
  { key: "diffView", label: "Diff view", options: ["unified", "split"] },
  { key: "mouseCapture", label: "Mouse", options: [...TOGGLES] },
];

export type SettingsApply = (next: SettingsState) => void;

export class SettingsWidget {
  readonly node: any;
  private panel: InfoPanelWidget;
  private current: SettingsState;
  private applyHandler: SettingsApply | null = null;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.panel = new InfoPanelWidget(opentui, ctx, theme);
    this.node = this.panel.node;
    this.current = {
      theme: "paper-dark",
      spinner: "braille",
      showReasoning: false,
      diffView: "unified",
      mouseCapture: true,
      rightRail: false,
      dirty: false,
    };
    this.panel.update(settingsContent(this.current));
  }

  update(settings: SettingsState): void {
    this.current = settings;
    this.panel.update(settingsContent(settings));
  }

  bindApply(handler: SettingsApply): void {
    this.applyHandler = handler;
  }

  setValue(key: keyof SettingsState, value: string): SettingsState {
    const next = { ...this.current, dirty: true };
    if (key === "showReasoning" || key === "mouseCapture") {
      next[key] = value === "on" || value === "true" || value === "1";
    } else if (key === "rightRail") {
      next.rightRail = false;
    } else if (key === "diffView") {
      next.diffView = value === "split" ? "split" : "unified";
    } else if (key === "theme" || key === "spinner") {
      next[key] = key === "spinner" ? normalizeSpinner(value) : value;
    } else {
      return this.current;
    }
    this.applyHandler?.(next);
    return next;
  }
}

function settingsContent(settings: SettingsState): InfoPanelContent {
  const rows = ROWS.map((row) => ({
    label: row.label,
    value: valueFor(row.key, settings),
    detail: detailFor(row, settings),
    tone: row.key === "theme" ? ("accent" as const) : undefined,
  }));
  if (settings.dirty) {
    rows.push({
      label: "save",
      value: "pending",
      detail: "changes not written to disk",
      tone: "warning" as const,
    });
  }
  return {
    eyebrow: "settings",
    rows,
  };
}

function detailFor(row: Row, settings: SettingsState): string {
  if (row.key === "theme") return "semantic layer only · widgets unchanged";
  if (row.key === "spinner") return "frame-based motion";
  if (row.key === "showReasoning") return settings.showReasoning ? "reasoning visible" : "reasoning folded";
  if (row.key === "diffView") return settings.diffView === "split" ? "split patch view" : "single patch view";
  if (row.key === "mouseCapture") return settings.mouseCapture ? "mouse and keyboard aligned" : "keyboard only";
  return row.options.join(" · ");
}

function valueFor(key: keyof SettingsState, settings: SettingsState): string {
  if (key === "showReasoning") return settings.showReasoning ? "visible" : "folded";
  const value = settings[key];
  if (typeof value === "boolean") return value ? "on" : "off";
  return String(value);
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
      spinner: normalizeSpinner(settings.spinner),
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
    const settings = (raw.settings ?? {}) as Partial<SettingsState>;
    return settings.spinner === undefined ? settings : { ...settings, spinner: normalizeSpinner(settings.spinner) };
  } catch {
    return {};
  }
}

export function normalizeSpinner(value: unknown): string {
  return SPINNERS.includes(String(value)) ? String(value) : "braille";
}
