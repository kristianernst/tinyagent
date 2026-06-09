import { frame } from "../design/borders";
import type { AppState, DiffState } from "../state/reducer";
import { activeTurn } from "../state/selectors";
import { renderApprovalModal } from "./ApprovalModal";
import { renderAcpPanel } from "./AcpPanel";
import { renderCommandPalette } from "./CommandPalette";
import { renderContextGraph } from "./ContextGraph";
import { renderDebugOverlay } from "./DebugOverlay";
import { renderDiffViewer } from "./DiffViewer";
import { renderModelLab } from "./ModelLab";
import { renderHeadlessPanel } from "./HeadlessPanel";
import { renderPlanBoard } from "./PlanBoard";
import { renderEvalLab } from "./EvalLab";
import { renderFailurePanel } from "./FailurePanel";
import { renderReplayCinema } from "./ReplayCinema";
import { renderSessionRail } from "./SessionRail";
import { renderSkillForge } from "./SkillForge";
import { renderToolTimeline } from "./ToolTimeline";
import { renderTranscript } from "./Transcript";
import { renderUsagePanel } from "./UsagePanel";
import { renderUpdatePanel } from "./UpdatePanel";

const ASSUMED_CONTEXT_WINDOW = 128_000;
const WARN_THRESHOLD = 80;
const DANGER_THRESHOLD = 95;
const METER_WIDTH = 5;
const METER_FILLED = "▰";
const METER_EMPTY = "▱";

export function renderRootShell(state: AppState): string {
  const session = state.activeSession;
  const turn = activeTurn(state);
  const transcript = renderPage(session);
  const workspace = state.workspaces.find((item) => item.workspace_id === state.activeWorkspaceId) ?? null;
  const panel = renderPanel(state, workspace);
  const approval = renderApprovalModal(session?.pendingApproval ?? null);
  const errors = state.errors.length ? frame("errors", state.errors.slice(-3).join("\n"), 100) : "";
  const debug = state.ui.debugOverlay ? `\n\n${frame("debug", renderDebugOverlay(state), 72)}` : "";
  return [
    renderChromeLine(state, workspace?.name ?? "—"),
    transcript,
    panel ? renderOverlay(state.ui.activePanel, panel) : "",
    errors,
    approval ? frame("approval", approval, 100, "heavy") : "",
    debug,
  ]
    .filter(Boolean)
    .join("\n");
}

function renderChromeLine(state: AppState, workspaceName: string): string {
  const branch = state.activeSession?.git?.branch ? ` │ ⎇ ${state.activeSession.git.branch}` : "";
  const tokens = state.activeSession?.usage?.totalTokens ?? 0;
  const pct = contextPercent(tokens);
  const transients = renderTransientPills(state);
  return `◆ tinyagent │ ws : ${workspaceName} │ model : ${state.model}${branch} │ ⦗ ${phaseLabel(state)} ⦘${transients} │ ${renderCtxMeter(pct)}`;
}

function renderPage(session: AppState["activeSession"]): string {
  const transcript = renderTranscript(session?.turns ?? []);
  const diff = renderInlineDiffSummary(session?.diff ?? null);
  return [transcript, diff].filter(Boolean).join("\n\n");
}

function renderInlineDiffSummary(diff: DiffState | null): string {
  if (!diff?.text && !diff?.omittedFiles) return "";
  return renderDiffSummary(diff);
}

function phaseLabel(state: AppState): string {
  if (state.phase === "approval") return "approve";
  if (state.phase === "failed") return "failed";
  if (state.phase === "thinking") return "thinking";
  if (state.phase === "streaming") return "streaming";
  if (state.sessionMode === "plan") return "plan";
  return "idle";
}

function contextPercent(tokens: number): number {
  return Math.min(100, Math.round((tokens / ASSUMED_CONTEXT_WINDOW) * 100));
}

function renderCtxMeter(pct: number): string {
  const filled = Math.max(0, Math.min(METER_WIDTH, Math.round((pct / 100) * METER_WIDTH)));
  const bar = METER_FILLED.repeat(filled) + METER_EMPTY.repeat(METER_WIDTH - filled);
  const suffix = pct >= DANGER_THRESHOLD ? " — danger" : pct >= WARN_THRESHOLD ? " — warning" : "";
  return `ctx ${bar} ${pct.toString().padStart(2)}%${suffix}`;
}

function renderTransientPills(state: AppState): string {
  const labels: string[] = [];
  const pct = contextPercent(state.activeSession?.usage?.totalTokens ?? 0);
  if (pct >= DANGER_THRESHOLD) labels.push("compact");
  if (state.activeSession?.pendingApproval && state.phase !== "approval") labels.push("approve queued");
  if (state.updatePanel.result?.available) labels.push(`update ${state.updatePanel.result.latest_version}`);
  if (state.sessionMode === "plan" && state.phase !== "idle") labels.push("plan");
  return labels.map((label) => ` ⦗ ${label} ⦘`).join("");
}

function renderOverlay(panel: AppState["ui"]["activePanel"], body: string): string {
  return [`┆ ${panel}`, ...body.split("\n").map((line) => `┆ ${line}`)].join("\n");
}

function renderPanel(state: AppState, workspace: AppState["workspaces"][number] | null): string {
  const session = state.activeSession;
  const turn = activeTurn(state);
  if (state.ui.activePanel === "transcript") return "";
  if (state.ui.activePanel === "sessions") return renderSessionRail(state.sessions);
  if (state.ui.activePanel === "context") return renderContextGraph(workspace, state.workspaceFiles, session?.git ?? null);
  if (state.ui.activePanel === "diff") return renderDiffViewer(session?.diff ?? null);
  if (state.ui.activePanel === "usage") return renderUsagePanel(session?.usage ?? { inputTokens: 0, outputTokens: 0, totalTokens: 0, modelCalls: 0, latencyMs: 0 });
  if (state.ui.activePanel === "model") return renderModelLab(state.provider, state.model);
  if (state.ui.activePanel === "replay") return renderReplayCinema(state.replay);
  if (state.ui.activePanel === "eval") return renderEvalLab(state.evalLab);
  if (state.ui.activePanel === "skills") return renderSkillForge(state.skillForge);
  if (state.ui.activePanel === "update") return renderUpdatePanel(state.updatePanel);
  if (state.ui.activePanel === "review") return renderFailurePanel(state.failure);
  if (state.ui.activePanel === "headless") return renderHeadlessPanel(state);
  if (state.ui.activePanel === "acp") return renderAcpPanel();
  if (state.ui.activePanel === "theme") return ["theme", diffRow("palette", state.ui.theme, "active colors"), diffRow("spinner", state.ui.spinner, "motion preset")].join("\n");
  if (state.ui.activePanel === "help") return renderCommandPalette();
  return [renderToolTimeline(turn?.tools ?? []), "", renderPlanBoard(state), "", renderDiffSummary(session?.diff ?? null)].join("\n");
}

function renderDiffSummary(diff: DiffState | null): string {
  if (!diff) return ["diff", diffRow("status", "empty", "no changes")].join("\n");
  const omitted = diff.omittedFiles ? ` · ${diff.omittedFiles} private file${diff.omittedFiles === 1 ? "" : "s"} omitted` : "";
  if (!diff.text) {
    return diff.omittedFiles
      ? ["diff", diffRow("status", "private only", `no text diff${omitted}`), diffRow("inspect", "/diff", "open patch view")].join("\n")
      : ["diff", diffRow("status", "empty", "no changes")].join("\n");
  }
  const count = diff.paths.length;
  const suffix = diff.truncated ? " truncated" : "";
  return [
    "diff",
    diffRow("files", count ? `${count} changed file${count === 1 ? "" : "s"}${suffix}` : `available${suffix}`, `inspect /diff${omitted}`),
  ].join("\n");
}

function diffRow(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}
