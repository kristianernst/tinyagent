import type { SettingsState } from "../state/reducer";
import type { Store } from "../state/store";
import { normalizeSpinner, saveSettings } from "../ui/widgets/SettingsWidget";

export function runSettingsCommand(store: Store, args: string[]): boolean {
  const action = args[0] ?? "show";
  const state = store.get();
  if (action === "save") {
    const ok = saveSettings(state.settings);
    if (ok) {
      store.set({ ...state, settings: { ...state.settings, dirty: false } });
    } else {
      store.set({ ...state, errors: [...state.errors, "Failed to save settings."] });
    }
    return ok;
  }
  if (action === "reset") {
    store.set({
      ...state,
      settings: {
        theme: "paper-dark",
        spinner: "braille",
        showReasoning: false,
        diffView: "unified",
        mouseCapture: true,
        rightRail: false,
        dirty: true,
      },
    });
    return true;
  }
  if (action === "set") {
    const key = args[1];
    const value = args[2];
    if (!key || value === undefined) {
      store.set({ ...state, errors: [...state.errors, "Usage: /settings set <key> <value>"] });
      return false;
    }
    const next = applyValue(state.settings, key, value);
    if (!next) {
      store.set({ ...state, errors: [...state.errors, `Unknown settings key: ${key}`] });
      return false;
    }
    store.set({ ...state, settings: next, ui: { ...state.ui, activePanel: "settings" } });
    return true;
  }
  // default: show panel
  store.set({ ...state, ui: { ...state.ui, activePanel: "settings" } });
  return true;
}

function applyValue(current: SettingsState, key: string, raw: string): SettingsState | null {
  const value = raw.trim();
  const next: SettingsState = { ...current, dirty: true };
  switch (key) {
    case "theme":
      next.theme = value;
      return next;
    case "spinner":
      next.spinner = normalizeSpinner(value);
      return next;
    case "diff":
    case "diffView":
      next.diffView = value === "split" ? "split" : "unified";
      return next;
    case "reasoning":
    case "showReasoning":
      next.showReasoning = boolish(value);
      return next;
    case "mouse":
    case "mouseCapture":
      next.mouseCapture = boolish(value);
      return next;
    case "rail":
    case "rightRail":
      // The persistent rail was removed by the Paper redesign. Keep these
      // keys accepted for old configs/commands, but never re-enable the split.
      next.rightRail = false;
      return next;
    default:
      return null;
  }
}

function boolish(value: string): boolean {
  return value === "on" || value === "true" || value === "1" || value === "yes";
}
