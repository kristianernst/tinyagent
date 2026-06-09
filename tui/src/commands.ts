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
  | "diff-stat"
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
  { id: "new", title: "start new session" },
  { id: "context", title: "show context", panel: "context" },
  { id: "diff", title: "show git diff", panel: "diff" },
  { id: "diff-stat", title: "show diff summary", panel: "diff" },
  { id: "replay", title: "replay current run", panel: "replay" },
  { id: "sessions", title: "list sessions", panel: "sessions" },
  { id: "skills", title: "open skill forge", panel: "skills", mutatesBackend: true },
  { id: "model", title: "show model state", panel: "model" },
  { id: "always-approve", title: "always approve" },
  { id: "resume", title: "resume session" },
  { id: "plan", title: "plan mode" },
  { id: "build", title: "build mode" },
  { id: "ask", title: "ask for approval" },
  { id: "approve", title: "approve pending tool", mutatesBackend: true },
  { id: "deny", title: "deny pending tool", mutatesBackend: true },
  { id: "compact-mode", title: "compact context", panel: "context" },
  { id: "usage", title: "show token usage", panel: "usage" },
  { id: "rewind", title: "rewind to event", panel: "replay" },
  { id: "fork", title: "fork from event", panel: "replay", mutatesBackend: true },
  { id: "review", title: "review failure", panel: "review" },
  { id: "eval", title: "run eval suite", panel: "eval", mutatesBackend: true },
  { id: "update", title: "check for update", panel: "update", mutatesBackend: true },
  { id: "headless", title: "show CLI commands", panel: "headless" },
  { id: "acp", title: "show ACP bridge", panel: "acp" },
  { id: "theme", title: "preview themes", panel: "theme" },
  { id: "stop", title: "stop run", mutatesBackend: true },
  { id: "debug", title: "show debug state", panel: "debug" },
  { id: "reason", title: "toggle reasoning" },
  { id: "rail", title: "list sessions" },
  { id: "palette", title: "open command palette" },
  { id: "settings", title: "open settings", panel: "settings", mutatesBackend: false },
  { id: "extensions", title: "show extensions", panel: "extensions", mutatesBackend: false },
  { id: "help", title: "show commands", panel: "help" },
];

const pickerCommandIds = [
  "new",
  "context",
  "diff",
  "diff-stat",
  "replay",
  "sessions",
  "skills",
  "model",
  "resume",
  "plan",
  "build",
  "usage",
  "review",
  "eval",
  "update",
  "headless",
  "acp",
  "theme",
  "help",
] as const satisfies readonly CommandId[];

// The parser accepts compatibility and low-level action commands; the picker
// stays curated to the Paper command surface so it remains scannable.
export const pickerCommands: Command[] = pickerCommandIds.map((id) => commands.find((command) => command.id === id)!);

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

export const themeCycle = ["paper-dark", "paper-light", "mono"] as const;

export function applyLocalCommand(state: AppState, id: CommandId): AppState {
  if (id === "plan") return { ...state, sessionMode: "plan" satisfies SessionMode };
  if (id === "build") return { ...state, sessionMode: "normal" satisfies SessionMode };
  if (id === "always-approve") return { ...state, approvalMode: "yolo" satisfies ApprovalMode };
  if (id === "ask") return { ...state, approvalMode: "on-request" satisfies ApprovalMode };
  if (id === "debug") return { ...state, ui: { ...state.ui, debugOverlay: !state.ui.debugOverlay } };
  if (id === "reason") return { ...state, ui: { ...state.ui, showReasoning: !state.ui.showReasoning } };
  // The Paper redesign removes the persistent split rail. Keep the command as
  // a compatibility alias for the sessions overlay.
  if (id === "rail") return { ...state, ui: { ...state.ui, rightRail: false, activePanel: "sessions" } };
  if (id === "palette") return { ...state, ui: { ...state.ui, paletteOpen: !state.ui.paletteOpen, activePanel: state.ui.paletteOpen ? state.ui.activePanel : "help" } };
  if (id === "theme") {
    const index = themeCycle.indexOf(state.ui.theme as (typeof themeCycle)[number]);
    const next = themeCycle[(index + 1 + themeCycle.length) % themeCycle.length] ?? "paper-dark";
    return { ...state, ui: { ...state.ui, theme: next, activePanel: "theme" } };
  }
  const command = commands.find((item) => item.id === id);
  if (command?.panel) return { ...state, ui: { ...state.ui, activePanel: command.panel } };
  return state;
}
