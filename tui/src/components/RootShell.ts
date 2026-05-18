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
import { renderStatusBar } from "./StatusBar";
import { renderToolTimeline } from "./ToolTimeline";
import { renderTranscript } from "./Transcript";
import { renderUsagePanel } from "./UsagePanel";
import { renderUpdatePanel } from "./UpdatePanel";

export function renderRootShell(state: AppState, tick = 0): string {
  const session = state.activeSession;
  const turn = activeTurn(state);
  const transcript = renderTranscript(session?.turns ?? []);
  const workspace = state.workspaces.find((item) => item.workspace_id === state.activeWorkspaceId) ?? null;
  const rail = renderRail(state, workspace);
  const approval = renderApprovalModal(session?.pendingApproval ?? null);
  const errors = state.errors.length ? frame("errors", state.errors.slice(-3).join("\n"), 100) : "";
  const debug = state.ui.debugOverlay ? `\n\n${frame("debug", renderDebugOverlay(state), 72)}` : "";
  return [
    frame("transcript", transcript, 100),
    frame("rail", rail, 100),
    errors,
    approval ? frame("approval", approval, 100) : "",
    renderStatusBar(state, tick),
    debug,
  ]
    .filter(Boolean)
    .join("\n");
}

function renderRail(state: AppState, workspace: AppState["workspaces"][number] | null): string {
  const session = state.activeSession;
  const turn = activeTurn(state);
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
  if (state.ui.activePanel === "theme") return `Theme: ${state.ui.theme}\nSpinner: ${state.ui.spinner}`;
  if (state.ui.activePanel === "help") return renderCommandPalette();
  return [
    renderToolTimeline(turn?.tools ?? []),
          "",
          renderPlanBoard(state),
          "",
          renderDiffSummary(session?.diff ?? null),
        ].join("\n");
}

function renderDiffSummary(diff: DiffState | null): string {
  if (!diff) return "No diff.";
  const omitted = diff.omittedFiles ? ` ${diff.omittedFiles} private file${diff.omittedFiles === 1 ? "" : "s"} omitted.` : "";
  if (!diff.text) return diff.omittedFiles ? `No displayable diff.${omitted} Use /diff to inspect.` : "No diff.";
  const count = diff.paths.length;
  const suffix = diff.truncated ? " truncated" : "";
  return count
    ? `Diff: ${count} changed file${count === 1 ? "" : "s"}${suffix}.${omitted} Use /diff to inspect.`
    : `Diff available${suffix}.${omitted} Use /diff to inspect.`;
}
