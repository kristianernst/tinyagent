import type { AppState } from "../../state/reducer";
import { renderAcpPanel } from "../../components/AcpPanel";
import { renderCommandPalette } from "../../components/CommandPalette";
import { renderHeadlessPanel } from "../../components/HeadlessPanel";
import { renderModelLab } from "../../components/ModelLab";
import { activeTurn } from "../../state/selectors";
import type { Theme } from "../theme";
import { makeBox, makeDiff, makeText, syntaxStyleFor } from "../layout";
import { ContextWidget } from "./ContextWidget";
import { DebugWidget } from "./DebugWidget";
import { EvalLabWidget } from "./EvalLabWidget";
import { ExtensionsWidget } from "./ExtensionsWidget";
import { FailureWidget } from "./FailureWidget";
import { PlanBoardWidget } from "./PlanBoardWidget";
import { ReplayWidget } from "./ReplayWidget";
import { SessionsWidget } from "./SessionsWidget";
import { SettingsWidget } from "./SettingsWidget";
import { SkillForgeWidget } from "./SkillForgeWidget";
import { ToolTimelineWidget } from "./ToolTimelineWidget";
import { UpdateWidget } from "./UpdateWidget";
import { UsageWidget } from "./UsageWidget";

type PanelKey =
  | "transcript"
  | "sessions"
  | "context"
  | "diff"
  | "usage"
  | "model"
  | "replay"
  | "eval"
  | "skills"
  | "update"
  | "review"
  | "headless"
  | "acp"
  | "theme"
  | "help"
  | "debug"
  | "settings"
  | "extensions";

export class RailWidget {
  readonly node: any;
  private title: any;
  private syntaxStyle: any;

  private fallbackText: any;
  private diffNode: any;
  private activityHeader: any;
  private tools: ToolTimelineWidget;
  private plan: PlanBoardWidget;
  private sessions: SessionsWidget;
  private replay: ReplayWidget;
  private failure: FailureWidget;
  private evalLab: EvalLabWidget;
  private skills: SkillForgeWidget;
  private updateW: UpdateWidget;
  private context: ContextWidget;
  private usage: UsageWidget;
  private debug: DebugWidget;
  private settings: SettingsWidget;
  private extensions: ExtensionsWidget;
  private panelNodes = new Map<PanelKey | "activity", any>();

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.syntaxStyle = syntaxStyleFor(opentui, theme);
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "single",
      border: true,
      borderColor: theme.border,
      focusedBorderColor: theme.borderFocus,
      paddingX: 1,
      paddingY: 0,
      backgroundColor: theme.surface,
      width: 56,
      minWidth: 40,
      focusable: true,
      title: " Rail ",
    });
    this.title = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.node.add?.(this.title);

    // Activity (default) — tool timeline + plan board.
    const activity = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.activityHeader = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.tools = new ToolTimelineWidget(opentui, ctx, theme);
    this.plan = new PlanBoardWidget(opentui, ctx, theme);
    activity.add?.(this.activityHeader);
    activity.add?.(this.tools.node);
    activity.add?.(this.plan.node);
    this.panelNodes.set("activity", activity);

    this.sessions = new SessionsWidget(opentui, ctx, theme);
    this.panelNodes.set("sessions", this.sessions.node);

    this.context = new ContextWidget(opentui, ctx, theme);
    this.panelNodes.set("context", this.context.node);

    this.diffNode = makeDiff(opentui, ctx, {
      diff: "",
      view: "unified",
      showLineNumbers: true,
      syntaxStyle: this.syntaxStyle,
      flexGrow: 1,
    });
    this.panelNodes.set("diff", this.diffNode);

    this.usage = new UsageWidget(opentui, ctx, theme);
    this.panelNodes.set("usage", this.usage.node);

    this.replay = new ReplayWidget(opentui, ctx, theme);
    this.panelNodes.set("replay", this.replay.node);

    this.evalLab = new EvalLabWidget(opentui, ctx, theme);
    this.panelNodes.set("eval", this.evalLab.node);

    this.skills = new SkillForgeWidget(opentui, ctx, theme);
    this.panelNodes.set("skills", this.skills.node);

    this.updateW = new UpdateWidget(opentui, ctx, theme);
    this.panelNodes.set("update", this.updateW.node);

    this.failure = new FailureWidget(opentui, ctx, theme);
    this.panelNodes.set("review", this.failure.node);

    this.debug = new DebugWidget(opentui, ctx, theme);
    this.panelNodes.set("debug", this.debug.node);

    this.settings = new SettingsWidget(opentui, ctx, theme);
    this.panelNodes.set("settings", this.settings.node);

    this.extensions = new ExtensionsWidget(opentui, ctx, theme);
    this.panelNodes.set("extensions", this.extensions.node);

    // Fallback text-only panels (model, headless, acp, theme, help)
    this.fallbackText = makeText(opentui, ctx, { content: "", fg: theme.text, flexGrow: 1 });

    // Mount all panel nodes (hidden by default) so we can toggle visibility per panel.
    for (const node of this.panelNodes.values()) {
      this.node.add?.(node);
      if (node && "visible" in node) node.visible = false;
      if (node && "enableLayout" in node) node.enableLayout = false;
    }
    this.node.add?.(this.fallbackText);
    if (this.fallbackText && "visible" in this.fallbackText) this.fallbackText.visible = false;
    if (this.fallbackText && "enableLayout" in this.fallbackText) this.fallbackText.enableLayout = false;
  }

  update(state: AppState): void {
    const panel = (state.ui.activePanel || "transcript") as PanelKey;
    const workspace = state.workspaces.find((item) => item.workspace_id === state.activeWorkspaceId) ?? null;
    const turn = activeTurn(state);
    const session = state.activeSession;
    const key: PanelKey | "activity" = panel === "transcript" ? "activity" : panel;
    const useFallback = key === "model" || key === "headless" || key === "acp" || key === "theme" || key === "help";
    for (const [name, node] of this.panelNodes) {
      const show = name === key && !useFallback;
      if (node && "visible" in node) node.visible = show;
      if (node && "enableLayout" in node) node.enableLayout = show;
    }
    if (this.fallbackText && "visible" in this.fallbackText) this.fallbackText.visible = useFallback;
    if (this.fallbackText && "enableLayout" in this.fallbackText) this.fallbackText.enableLayout = useFallback;
    if (this.title && this.title.content !== undefined) this.title.content = panelTitle(panel);

    if (key === "activity") {
      if (this.activityHeader && this.activityHeader.content !== undefined) {
        const tools = turn?.tools.length ?? 0;
        this.activityHeader.content = tools ? `${tools} tool call${tools === 1 ? "" : "s"}` : "No tool calls yet.";
      }
      this.tools.update(turn?.tools ?? []);
      this.plan.update(state);
      return;
    }

    switch (key) {
      case "sessions":
        this.sessions.update(state.sessions);
        return;
      case "context":
        this.context.update(workspace, state.workspaceFiles, session?.git ?? null);
        return;
      case "diff":
        if (this.diffNode) {
          if ("diff" in this.diffNode) this.diffNode.diff = session?.diff?.text ?? "";
          if ("view" in this.diffNode) this.diffNode.view = state.ui.diffView ?? "unified";
        }
        return;
      case "usage":
        this.usage.update(session?.usage ?? { inputTokens: 0, outputTokens: 0, totalTokens: 0, modelCalls: 0, latencyMs: 0 });
        return;
      case "replay":
        this.replay.update(state.replay);
        return;
      case "eval":
        this.evalLab.update(state.evalLab);
        return;
      case "skills":
        this.skills.update(state.skillForge);
        return;
      case "update":
        this.updateW.update(state.updatePanel);
        return;
      case "review":
        this.failure.update(state.failure);
        return;
      case "debug":
        this.debug.update(state);
        return;
      case "settings":
        this.settings.update(state.settings);
        return;
      case "extensions":
        this.extensions.update(state.extensions);
        return;
      case "model":
        if (this.fallbackText && this.fallbackText.content !== undefined) {
          this.fallbackText.content = renderModelLab(state.provider, state.model);
        }
        return;
      case "headless":
      case "acp":
      case "theme":
      case "help":
      default:
        if (this.fallbackText && this.fallbackText.content !== undefined) {
          this.fallbackText.content = fallbackContent(panel, state);
        }
        return;
    }
  }
}

function panelTitle(panel: string): string {
  return ` ${panel ? panel[0].toUpperCase() + panel.slice(1) : "Rail"} `;
}

function fallbackContent(panel: string, state: AppState): string {
  if (panel === "headless") return renderHeadlessPanel(state);
  if (panel === "acp") return renderAcpPanel();
  if (panel === "theme") return `Theme: ${state.ui.theme}\nSpinner: ${state.ui.spinner}\n/theme to cycle.`;
  if (panel === "help") return renderCommandPalette();
  return "";
}
