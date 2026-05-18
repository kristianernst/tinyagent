import type {
  Approval,
  ApprovalMode,
  Artifact,
  Conversation,
  ConversationTurn,
  EvalResult,
  GitSnapshot,
  RunEvent,
  SessionMode,
  SkillDraft,
  UpdateStatus,
  Workspace,
} from "../protocol/events";
import { eventText, isUserVisible } from "../protocol/events";

export type ToolStatus = "running" | "done" | "failed" | "blocked" | "cancelled";
export type TurnPhase = "thinking" | "streaming" | "approval" | "done" | "failed" | "cancelled";
export type AppPhase = "idle" | "thinking" | "streaming" | "approval" | "failed";

export type ReasoningBlock = {
  id: string;
  text: string;
  completed: boolean;
};

export type ToolCallView = {
  id: string;
  tool: string;
  label: string;
  argsSummary: string;
  status: ToolStatus;
  output: string;
  startedAt?: string;
  completedAt?: string;
};

export type DiffState = {
  text: string;
  paths: string[];
  truncated: boolean;
  omittedFiles?: number;
};

export type UsageStats = {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  modelCalls: number;
  latencyMs: number;
};

export type ReplayProjection = {
  phase: AppPhase;
  lastSeq: number;
  turns: number;
  tools: number;
  assistantPreview: string;
};

export type ReplayState = {
  runId: string;
  events: RunEvent[];
  cursorSeq: number;
  rawEvent: RunEvent | null;
  projected: ReplayProjection | null;
  forkDir: string;
  replayMs: number;
};

export type EvalLabState = {
  status: "idle" | "running" | "completed" | "failed";
  suitePath: string;
  outputDir: string;
  report: string;
  results: EvalResult[];
  error: string;
  command: string;
};

export type SkillForgeState = {
  status: "idle" | "loading" | "ready" | "failed";
  drafts: SkillDraft[];
  selectedDraftId: string;
  markdown: string;
  lastAction: string;
  error: string;
};

export type UpdatePanelState = {
  status: "idle" | "checking" | "ready" | "applying" | "failed";
  result: UpdateStatus | null;
  lastAction: string;
  error: string;
};

export type SkillEntry = {
  name: string;
  path: string;
  description?: string;
};

export type ExtensionEntry = {
  name: string;
  kind: "mcp" | "lsp" | "feature" | "other";
  servers?: string[];
  enabled?: boolean;
  description?: string;
};

export type MentionTrigger = "/" | "@" | "$";

export type MentionState = {
  trigger: MentionTrigger | null;
  query: string;
  index: number;
};

export type SettingsState = {
  theme: string;
  spinner: string;
  showReasoning: boolean;
  diffView: "unified" | "split";
  mouseCapture: boolean;
  rightRail: boolean;
  dirty: boolean;
};

export type FailureExplanation = {
  source: string;
  lastSuccessfulEvent: string;
  failedEvent: string;
  recoveryActions: string[];
};

export type TurnState = {
  id: string;
  runId: string | null;
  user: string;
  assistant: string;
  reasoning: ReasoningBlock[];
  tools: ToolCallView[];
  phase: TurnPhase;
  startedAt: string;
  completedAt: string;
};

export type SessionState = {
  conversationId: string;
  runId: string | null;
  runPath: string;
  turns: TurnState[];
  pendingApproval: Approval | null;
  artifacts: Artifact[];
  git: GitSnapshot | null;
  diff: DiffState | null;
  usage: UsageStats;
  lastSeq: number;
  eventsBySeq: Map<number, RunEvent>;
};

export type UiState = {
  rightRail: boolean;
  commandPalette: boolean;
  debugOverlay: boolean;
  mode: "footer" | "fullscreen";
  theme: string;
  spinner: string;
  activePanel: string;
  showReasoning: boolean;
  paletteOpen: boolean;
  diffView: "unified" | "split";
};

export type AppState = {
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  workspaceFiles: string[];
  sessions: Conversation[];
  activeSession: SessionState | null;
  provider: string;
  model: string;
  phase: AppPhase;
  approvalMode: ApprovalMode;
  sessionMode: SessionMode;
  replay: ReplayState | null;
  evalLab: EvalLabState;
  skillForge: SkillForgeState;
  updatePanel: UpdatePanelState;
  failure: FailureExplanation | null;
  skills: SkillEntry[];
  extensions: ExtensionEntry[];
  settings: SettingsState;
  mention: MentionState;
  ui: UiState;
  errors: string[];
};

export function emptyState(): AppState {
  return {
    workspaces: [],
    activeWorkspaceId: null,
    workspaceFiles: [],
    sessions: [],
    activeSession: null,
    provider: "tinyagent",
    model: "default",
    phase: "idle",
    approvalMode: "on-request",
    sessionMode: "normal",
    replay: null,
    evalLab: {
      status: "idle",
      suitePath: "",
      outputDir: "",
      report: "",
      results: [],
      error: "",
      command: "",
    },
    skillForge: {
      status: "idle",
      drafts: [],
      selectedDraftId: "",
      markdown: "",
      lastAction: "",
      error: "",
    },
    updatePanel: {
      status: "idle",
      result: null,
      lastAction: "",
      error: "",
    },
    failure: null,
    skills: [],
    extensions: [],
    settings: {
      theme: "tiny-dark",
      spinner: "ascii",
      showReasoning: false,
      diffView: "unified",
      mouseCapture: true,
      rightRail: true,
      dirty: false,
    },
    mention: { trigger: null, query: "", index: 0 },
    ui: {
      rightRail: true,
      commandPalette: false,
      debugOverlay: false,
      mode: "footer",
      theme: "tiny-dark",
      spinner: "ascii",
      activePanel: "transcript",
      showReasoning: false,
      paletteOpen: false,
      diffView: "unified",
    },
    errors: [],
  };
}

export function createSession(conversationId: string): SessionState {
  return {
    conversationId,
    runId: null,
    runPath: "",
    turns: [],
    pendingApproval: null,
    artifacts: [],
    git: null,
    diff: null,
    usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, modelCalls: 0, latencyMs: 0 },
    lastSeq: 0,
    eventsBySeq: new Map(),
  };
}

export function sessionFromConversationTurns(conversationId: string, turns: ConversationTurn[]): SessionState {
  let session = createSession(conversationId);
  for (const item of turns) {
    const turnId = item.turn_id ?? `${conversationId}-${session.turns.length + 1}`;
    const user = messageContent(item.user_message);
    const assistant = assistantPreview(item.assistant_message);
    const status = item.status ?? "completed";
    session = upsertTurn(session, turnId, (turn) => ({
      ...turn,
      id: turnId,
      runId: item.run_id ?? turn.runId,
      user: user || turn.user,
      assistant: assistant || turn.assistant,
      phase: turnPhaseFromStatus(status),
      startedAt: item.created_at ?? turn.startedAt,
      completedAt: item.completed_at ?? turn.completedAt,
      tools: toolSummaryFromTurn(item),
    }));
    session = { ...session, runId: item.run_id ?? session.runId };
    session = { ...session, runPath: item.run_path ?? session.runPath };
  }
  return session;
}

export function reduceEvent(state: AppState, event: RunEvent): AppState {
  const session = ensureSession(state, event);
  const nextSession: SessionState = {
    ...session,
    runId: event.run_id || session.runId,
    lastSeq: Math.max(session.lastSeq, event.seq ?? 0),
    eventsBySeq: new Map(session.eventsBySeq).set(event.seq, event),
  };
  let next: AppState = { ...state, activeSession: nextSession };
  const data = event.data ?? {};

  switch (event.type) {
    case "run.started": {
      const turnId = event.turn_id || eventText(event, "turn_id") || `turn_${event.run_id}`;
      const task = eventText(event, "task");
      next.activeSession = upsertTurn(nextSession, turnId, (turn) => ({
        ...turn,
        id: turnId,
        runId: event.run_id,
        user: turn.user || task,
        phase: "thinking",
        startedAt: event.time || turn.startedAt,
      }));
      return { ...next, phase: "thinking" };
    }
    case "turn.started": {
      const turnId = event.turn_id || eventText(event, "turn_id") || `turn_${event.run_id}`;
      next.activeSession = upsertTurn(nextSession, turnId, (turn) => ({ ...turn, phase: "thinking" }));
      return { ...next, phase: "thinking" };
    }
    case "model.call.started":
      return { ...next, phase: "thinking" };
    case "model.reasoning.delta": {
      if (!isUserVisible(event)) return next;
      const delta = eventText(event, "delta");
      if (!delta) return next;
      const blockId = reasoningId(event);
      return updateActiveTurn(next, event, (turn) => ({
        ...turn,
        reasoning: appendReasoningDelta(turn.reasoning, blockId, delta),
        phase: "thinking",
      }), "thinking");
    }
    case "model.reasoning.completed": {
      if (!isUserVisible(event)) return next;
      const text = eventText(event, "reason") || eventText(event, "text");
      if (!text) return next;
      const blockId = reasoningId(event);
      return updateActiveTurn(next, event, (turn) => ({
        ...turn,
        reasoning: completeReasoning(turn.reasoning, blockId, text),
      }));
    }
    case "model.text.delta": {
      const delta = eventText(event, "delta");
      if (!delta) return next;
      return updateActiveTurn(next, event, (turn) => ({
        ...turn,
        assistant: turn.assistant + delta,
        phase: "streaming",
      }), "streaming");
    }
    case "model.message.completed": {
      const text = eventText(event, "text");
      return updateActiveTurn(next, event, (turn) => ({
        ...turn,
        assistant: turn.assistant || text,
        phase: turn.phase === "thinking" ? "streaming" : turn.phase,
      }), "streaming");
    }
    case "model.tool_call.assembly.completed":
    case "tool.execution.started": {
      const tool = String(data.tool ?? data.tool_name ?? "tool");
      const toolId = toolStepId(event);
      return updateActiveTurn(next, event, (turn) => ({
        ...turn,
        tools: upsertTool(turn.tools, toolId, {
          id: toolId,
          tool,
          label: summarizeTool(tool, data),
          argsSummary: summarizeArgs(data.args ?? data),
          status: "running",
          output: "",
          startedAt: event.time,
        }),
      }), "thinking");
    }
    case "tool.execution.output.delta":
    case "tool.execution.output.snapshot": {
      const toolId = toolStepId(event);
      const output = eventText(event, "delta") || eventText(event, "output") || eventText(event, "content_preview");
      return updateActiveTurn(next, event, (turn) => ({
        ...turn,
        tools: turn.tools.map((tool) => (tool.id === toolId ? { ...tool, output: event.type.endsWith("delta") ? tool.output + output : output } : tool)),
      }));
    }
    case "tool.execution.completed":
    case "tool.execution.failed":
    case "tool.execution.blocked":
    case "tool.execution.cancelled": {
      const toolId = toolStepId(event);
      const output = eventText(event, "output") || eventText(event, "summary") || eventText(event, "content_preview");
      return updateActiveTurn(next, event, (turn) => ({
        ...turn,
        tools: upsertTool(turn.tools, toolId, {
          id: toolId,
          tool: String(data.tool ?? "tool"),
          label: summarizeTool(String(data.tool ?? "tool"), data),
          argsSummary: summarizeArgs(data.args ?? data),
          status: statusForToolEvent(event.type),
          output,
          completedAt: event.time,
        }),
      }));
    }
    case "approval.requested": {
      const approval = approvalFromEvent(event);
      next.activeSession = { ...next.activeSession!, pendingApproval: approval };
      return updateActiveTurn({ ...next, phase: "approval" }, event, (turn) => ({ ...turn, phase: "approval" }));
    }
    case "approval.resolved":
    case "approval.expired": {
      const approvalId = String(data.approval_id ?? "");
      const pending = next.activeSession!.pendingApproval;
      next.activeSession = { ...next.activeSession!, pendingApproval: pending?.approval_id === approvalId ? null : pending };
      return { ...next, phase: "thinking" };
    }
    case "artifact.created":
    case "artifact.materialized": {
      const artifact = artifactFromEvent(event);
      next.activeSession = { ...next.activeSession!, artifacts: upsertByPath(next.activeSession!.artifacts, artifact) };
      return next;
    }
    case "patch.applied":
    case "file.edited":
    case "diff.finalized": {
      const paths = Array.isArray(data.paths) ? data.paths.map(String) : [];
      const text = eventText(event, "diff") || eventText(event, "output") || eventText(event, "content_preview");
      next.activeSession = {
        ...next.activeSession!,
        diff: {
          text: bounded(text, 200_000),
          paths,
          truncated: text.length > 200_000 || Boolean(data.truncated),
        },
      };
      return next;
    }
    case "model.usage": {
      const usage = next.activeSession!.usage;
      const input = numeric(data.input_tokens ?? data.prompt_tokens);
      const output = numeric(data.output_tokens ?? data.completion_tokens);
      const total = numeric(data.total_tokens) || input + output;
      next.activeSession = {
        ...next.activeSession!,
        usage: {
          inputTokens: usage.inputTokens + input,
          outputTokens: usage.outputTokens + output,
          totalTokens: usage.totalTokens + total,
          modelCalls: usage.modelCalls + 1,
          latencyMs: usage.latencyMs + numeric(data.latency_ms),
        },
      };
      return next;
    }
    case "run.completed":
      return updateActiveTurn({ ...next, phase: "idle" }, event, (turn) => ({ ...turn, phase: "done", completedAt: event.time || turn.completedAt }));
    case "run.failed":
      return updateActiveTurn({ ...next, phase: "failed" }, event, (turn) => ({ ...turn, phase: "failed", completedAt: event.time || turn.completedAt }));
    case "run.cancelled":
      return updateActiveTurn({ ...next, phase: "idle" }, event, (turn) => ({ ...turn, phase: "cancelled", completedAt: event.time || turn.completedAt }));
    default:
      return next;
  }
}

export function replayEvents(initial: AppState, events: Iterable<RunEvent>): AppState {
  let state = initial;
  for (const event of events) state = reduceEvent(state, event);
  return state;
}

function ensureSession(state: AppState, event: RunEvent): SessionState {
  if (state.activeSession) return state.activeSession;
  return createSession(event.conversation_id || "local");
}

function updateActiveTurn(state: AppState, event: RunEvent, fn: (turn: TurnState) => TurnState, phase?: AppPhase): AppState {
  const session = ensureSession(state, event);
  const turnId = event.turn_id || session.turns[session.turns.length - 1]?.id || `turn_${event.run_id}`;
  return {
    ...state,
    phase: phase ?? state.phase,
    activeSession: upsertTurn(session, turnId, fn),
  };
}

function upsertTurn(session: SessionState, turnId: string, fn: (turn: TurnState) => TurnState): SessionState {
  const index = session.turns.findIndex((turn) => turn.id === turnId);
  if (index === -1) {
    return {
      ...session,
      turns: [
        ...session.turns,
        fn({ id: turnId, runId: session.runId, user: "", assistant: "", reasoning: [], tools: [], phase: "thinking", startedAt: "", completedAt: "" }),
      ],
    };
  }
  const turns = session.turns.slice();
  turns[index] = fn(turns[index]);
  return { ...session, turns };
}

function messageContent(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const content = (value as { content?: unknown }).content;
  return typeof content === "string" ? content : "";
}

function assistantPreview(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const preview = (value as { content_preview?: unknown }).content_preview;
  return typeof preview === "string" ? preview : "";
}

function toolSummaryFromTurn(item: ConversationTurn): ToolCallView[] {
  const summary = (item as { tool_summary?: unknown }).tool_summary;
  if (!Array.isArray(summary)) return [];
  return summary.map((tool, index) => {
    const row = tool && typeof tool === "object" ? (tool as Record<string, unknown>) : {};
    return {
      id: String(row.tool_call_id ?? `${item.turn_id ?? "turn"}-tool-${index}`),
      tool: String(row.tool ?? "tool"),
      label: String(row.tool ?? "tool"),
      argsSummary: "",
      status: row.ok === false ? "failed" : row.blocked ? "blocked" : row.cancelled ? "cancelled" : "done",
      output: "",
    };
  });
}

function turnPhaseFromStatus(status: string): TurnPhase {
  if (status === "failed") return "failed";
  if (status === "cancelled") return "cancelled";
  if (status === "running") return "thinking";
  return "done";
}

function appendReasoningDelta(blocks: ReasoningBlock[], id: string, delta: string): ReasoningBlock[] {
  const index = blocks.findIndex((block) => block.id === id);
  if (index === -1) return [...blocks, { id, text: delta, completed: false }];
  const next = blocks.slice();
  next[index] = { ...next[index], text: next[index].text + delta };
  return next;
}

function completeReasoning(blocks: ReasoningBlock[], id: string, text: string): ReasoningBlock[] {
  const index = blocks.findIndex((block) => block.id === id);
  if (index === -1) return [...blocks, { id, text, completed: true }];
  const next = blocks.slice();
  next[index] = { ...next[index], text: next[index].text || text, completed: true };
  return next;
}

function upsertTool(tools: ToolCallView[], id: string, patch: ToolCallView): ToolCallView[] {
  const index = tools.findIndex((tool) => tool.id === id);
  if (index === -1) return [...tools, patch];
  const next = tools.slice();
  next[index] = { ...next[index], ...patch, output: patch.output || next[index].output };
  return next;
}

function toolStepId(event: RunEvent): string {
  return String(event.data.tool_call_id ?? event.item_id ?? event.id);
}

function reasoningId(event: RunEvent): string {
  return String(event.data.model_call_id ?? event.item_id ?? event.id);
}

function summarizeTool(tool: string, data: Record<string, unknown>): string {
  const args = summarizeArgs(data.args ?? data);
  return args ? `${tool} ${args}` : tool;
}

function summarizeArgs(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const data = value as Record<string, unknown>;
  if (typeof data.cmd === "string") return data.cmd;
  if (typeof data.patch === "string") return "patch";
  try {
    const rendered = JSON.stringify(data);
    return rendered.length > 96 ? `${rendered.slice(0, 96)}...` : rendered;
  } catch {
    return "";
  }
}

function statusForToolEvent(type: string): ToolStatus {
  if (type === "tool.execution.completed") return "done";
  if (type === "tool.execution.failed") return "failed";
  if (type === "tool.execution.cancelled") return "cancelled";
  return "blocked";
}

function approvalFromEvent(event: RunEvent): Approval {
  const data = event.data;
  return {
    approval_id: String(data.approval_id ?? ""),
    run_id: event.run_id,
    turn_id: event.turn_id,
    step_id: typeof data.step_id === "string" ? data.step_id : null,
    action_kind: String(data.action_kind ?? "unknown"),
    tool_name: String(data.tool_name ?? data.tool ?? "tool"),
    cwd: String(data.cwd ?? ""),
    args_preview: String(data.args_preview ?? ""),
    command: typeof data.command === "string" ? data.command : null,
    risk: String(data.risk ?? "medium"),
  };
}

function artifactFromEvent(event: RunEvent): Artifact {
  return {
    path: String(event.data.path ?? event.data.output_path ?? event.item_id ?? event.id),
    kind: String(event.data.kind ?? "artifact"),
    bytes: numeric(event.data.bytes),
    created_at: event.time,
    safe_to_display: event.data.safe_to_display !== false,
  };
}

function upsertByPath(items: Artifact[], item: Artifact): Artifact[] {
  const index = items.findIndex((candidate) => candidate.path === item.path);
  if (index === -1) return [item, ...items];
  const next = items.slice();
  next[index] = { ...next[index], ...item };
  return next;
}

function numeric(value: unknown): number {
  const number = Number(value ?? 0);
  return Number.isFinite(number) ? number : 0;
}

function bounded(text: string, limit: number): string {
  return text.length > limit ? text.slice(0, limit) : text;
}
