import type { ApprovalMode, SessionMode } from "./protocol/events";
import type { AppState } from "./state/reducer";

export type CommandId =
  | "new"
  | "sessions"
  | "resume"
  | "context"
  | "model"
  | "plan"
  | "build"
  | "always-approve"
  | "ask"
  | "approve"
  | "deny"
  | "compact-mode"
  | "usage"
  | "replay"
  | "rewind"
  | "fork"
  | "review"
  | "eval"
  | "skills"
  | "update"
  | "headless"
  | "acp"
  | "theme"
  | "stop"
  | "diff"
  | "debug"
  | "reason"
  | "rail"
  | "palette"
  | "settings"
  | "extensions"
  | "help";

export type Command = {
  id: CommandId;
  title: string;
  panel?: string;
  mutatesBackend?: boolean;
};

export type ParsedCommand = {
  id: CommandId;
  args: string[];
};

export const commands: Command[] = [
  { id: "new", title: "New session" },
  { id: "sessions", title: "Session browser", panel: "sessions" },
  { id: "resume", title: "Resume session" },
  { id: "context", title: "Context graph", panel: "context" },
  { id: "model", title: "Model switcher", panel: "model" },
  { id: "plan", title: "Plan mode" },
  { id: "build", title: "Build mode" },
  { id: "always-approve", title: "Always approve" },
  { id: "ask", title: "Ask for approval" },
  { id: "approve", title: "Approve pending tool", mutatesBackend: true },
  { id: "deny", title: "Deny pending tool", mutatesBackend: true },
  { id: "compact-mode", title: "Compact mode", panel: "context" },
  { id: "usage", title: "Usage panel", panel: "usage" },
  { id: "replay", title: "Replay cinema", panel: "replay" },
  { id: "rewind", title: "Rewind event", panel: "replay" },
  { id: "fork", title: "Fork from event", panel: "replay", mutatesBackend: true },
  { id: "review", title: "Failure review", panel: "review" },
  { id: "eval", title: "Eval lab", panel: "eval", mutatesBackend: true },
  { id: "skills", title: "Skill forge", panel: "skills", mutatesBackend: true },
  { id: "update", title: "Update manager", panel: "update", mutatesBackend: true },
  { id: "headless", title: "Headless parity", panel: "headless" },
  { id: "acp", title: "ACP bridge", panel: "acp" },
  { id: "theme", title: "Theme switcher", panel: "theme" },
  { id: "stop", title: "Stop run", mutatesBackend: true },
  { id: "diff", title: "Diff forge", panel: "diff" },
  { id: "debug", title: "Debug overlay", panel: "debug" },
  { id: "reason", title: "Toggle internal reasoning" },
  { id: "rail", title: "Toggle right rail" },
  { id: "palette", title: "Toggle command palette" },
  { id: "settings", title: "Settings", panel: "settings", mutatesBackend: false },
  { id: "extensions", title: "Extensions", panel: "extensions", mutatesBackend: false },
  { id: "help", title: "Command map", panel: "help" },
];

export const plannedCommands = [
  "compact",
  "memory",
] as const;

export function parseCommand(input: string): CommandId | null {
  return parseCommandInput(input)?.id ?? null;
}

export function parseCommandInput(input: string): ParsedCommand | null {
  const match = input.trim().match(/^\/([a-z-]+)/);
  if (!match) return null;
  const id = match[1] as CommandId;
  if (!commands.some((command) => command.id === id)) return null;
  const args = input.trim().slice(match[0].length).trim();
  return { id, args: args ? args.split(/\s+/) : [] };
}

export const themeCycle = ["tiny-dark", "tiny-light", "dracula", "gruvbox"] as const;

export function applyLocalCommand(state: AppState, id: CommandId): AppState {
  if (id === "plan") return { ...state, sessionMode: "plan" satisfies SessionMode };
  if (id === "build") return { ...state, sessionMode: "normal" satisfies SessionMode };
  if (id === "always-approve") return { ...state, approvalMode: "yolo" satisfies ApprovalMode };
  if (id === "ask") return { ...state, approvalMode: "on-request" satisfies ApprovalMode };
  if (id === "debug") return { ...state, ui: { ...state.ui, debugOverlay: !state.ui.debugOverlay } };
  if (id === "reason") return { ...state, ui: { ...state.ui, showReasoning: !state.ui.showReasoning } };
  if (id === "rail") return { ...state, ui: { ...state.ui, rightRail: !state.ui.rightRail } };
  if (id === "palette") return { ...state, ui: { ...state.ui, paletteOpen: !state.ui.paletteOpen, activePanel: state.ui.paletteOpen ? state.ui.activePanel : "help" } };
  if (id === "theme") {
    const index = themeCycle.indexOf(state.ui.theme as (typeof themeCycle)[number]);
    const next = themeCycle[(index + 1 + themeCycle.length) % themeCycle.length] ?? "tiny-dark";
    return { ...state, ui: { ...state.ui, theme: next, activePanel: "theme" } };
  }
  const command = commands.find((item) => item.id === id);
  if (command?.panel) return { ...state, ui: { ...state.ui, activePanel: command.panel } };
  return state;
}
