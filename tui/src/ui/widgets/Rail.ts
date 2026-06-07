import type { AppState } from "../../state/reducer";
import type { CommandId } from "../../commands";
import { glyphs } from "../../design/glyphs";
import { activeTurn } from "../../state/selectors";
import type { Theme } from "../theme";
import { makeBox, makeText, syntaxStyleFor } from "../layout";
import { CommandMapWidget } from "./CommandMapWidget";
import { ContextWidget } from "./ContextWidget";
import { DebugWidget } from "./DebugWidget";
import { DiffWidget } from "./DiffWidget";
import { EvalLabWidget } from "./EvalLabWidget";
import { ExtensionsWidget } from "./ExtensionsWidget";
import { FailureWidget } from "./FailureWidget";
import { InfoPanelWidget, type InfoPanelContent } from "./InfoPanelWidget";
import { PlanBoardWidget } from "./PlanBoardWidget";
import { ReplayWidget } from "./ReplayWidget";
import { SessionsWidget } from "./SessionsWidget";
import { SettingsWidget } from "./SettingsWidget";
import { SkillForgeWidget } from "./SkillForgeWidget";
import { ThemePanelWidget } from "./ThemePanelWidget";
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
  private count: any;
  private content: any;
  private footer: any;
  private syntaxStyle: any;
  private visible = false;
  private activePanel: PanelKey = "transcript";

  private fallbackText: any;
  private diffPanel: DiffWidget;
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
  private commands: CommandMapWidget;
  private modelPanel: InfoPanelWidget;
  private headlessPanel: InfoPanelWidget;
  private acpPanel: InfoPanelWidget;
  private themePanel: ThemePanelWidget;
  private panelNodes = new Map<PanelKey | "activity", any>();

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.syntaxStyle = syntaxStyleFor(opentui, theme);
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      position: "absolute",
      top: 1,
      right: 0,
      bottom: 0,
      zIndex: 60,
      borderStyle: "single",
      border: ["left"],
      borderColor: theme.borderStrong ?? theme.border,
      focusedBorderColor: theme.borderFocus,
      paddingX: 0,
      paddingY: 0,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
      width: 80,
      height: "100%",
      minWidth: 42,
      maxWidth: 80,
      focusable: true,
      visible: false,
      enableLayout: false,
    });
    const header = makeBox(opentui, ctx, {
      flexDirection: "row",
      alignItems: "center",
      height: 3,
      paddingX: 2,
      borderStyle: "single",
      border: ["bottom"],
      borderColor: theme.borderStrong ?? theme.border,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
      flexShrink: 0,
    });
    this.title = makeText(opentui, ctx, { content: "", fg: theme.text });
    header.add?.(this.title);
    this.count = makeText(opentui, ctx, { content: "", fg: theme.accent, bg: theme.accentSoft, marginLeft: 1 });
    header.add?.(this.count);
    header.add?.(makeBox(opentui, ctx, { flexGrow: 1 }));
    header.add?.(makeText(opentui, ctx, { content: `${glyphs.kbdL}esc${glyphs.kbdR} close`, fg: theme.textSubtle }));
    this.node.add?.(header);

    this.content = makeBox(opentui, ctx, {
      flexDirection: "column",
      flexGrow: 1,
      paddingX: 2,
      paddingY: 1,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
    });
    this.node.add?.(this.content);

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

    this.diffPanel = new DiffWidget(opentui, ctx, theme, this.syntaxStyle);
    this.panelNodes.set("diff", this.diffPanel.node);

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

    this.commands = new CommandMapWidget(opentui, ctx, theme);
    this.panelNodes.set("help", this.commands.node);

    this.modelPanel = new InfoPanelWidget(opentui, ctx, theme);
    this.panelNodes.set("model", this.modelPanel.node);

    this.headlessPanel = new InfoPanelWidget(opentui, ctx, theme);
    this.panelNodes.set("headless", this.headlessPanel.node);

    this.acpPanel = new InfoPanelWidget(opentui, ctx, theme);
    this.panelNodes.set("acp", this.acpPanel.node);

    this.themePanel = new ThemePanelWidget(opentui, ctx, theme);
    this.panelNodes.set("theme", this.themePanel.node);

    // Unknown panels still fail soft instead of leaving stale panel content visible.
    this.fallbackText = makeText(opentui, ctx, { content: "", fg: theme.text, flexGrow: 1 });

    // Mount all panel nodes (hidden by default) so we can toggle visibility per panel.
    for (const node of this.panelNodes.values()) {
      this.content.add?.(node);
      if (node && "visible" in node) node.visible = false;
      if (node && "enableLayout" in node) node.enableLayout = false;
    }
    this.content.add?.(this.fallbackText);
    if (this.fallbackText && "visible" in this.fallbackText) this.fallbackText.visible = false;
    if (this.fallbackText && "enableLayout" in this.fallbackText) this.fallbackText.enableLayout = false;

    const footerWrap = makeBox(opentui, ctx, {
      flexDirection: "row",
      alignItems: "center",
      height: 3,
      paddingX: 2,
      borderStyle: "single",
      border: ["top"],
      borderColor: theme.borderStrong ?? theme.border,
      backgroundColor: theme.surfaceOverlay ?? theme.surface,
      flexShrink: 0,
    });
    this.footer = makeText(opentui, ctx, { content: hintLine(), fg: theme.textSubtle });
    footerWrap.add?.(this.footer);
    this.node.add?.(footerWrap);
  }

  update(state: AppState): void {
    const panel = (state.ui.activePanel || "transcript") as PanelKey;
    this.activePanel = panel;
    const open = panel !== "transcript";
    this.setVisible(open);
    if (!open) return;

    const workspace = state.workspaces.find((item) => item.workspace_id === state.activeWorkspaceId) ?? null;
    const turn = activeTurn(state);
    const session = state.activeSession;
    const key: PanelKey | "activity" = panel;
    const useFallback = !this.panelNodes.has(key);
    for (const [name, node] of this.panelNodes) {
      const show = name === key && !useFallback;
      if (node && "visible" in node) node.visible = show;
      if (node && "enableLayout" in node) node.enableLayout = show;
    }
    if (this.fallbackText && "visible" in this.fallbackText) this.fallbackText.visible = useFallback;
    if (this.fallbackText && "enableLayout" in this.fallbackText) this.fallbackText.enableLayout = useFallback;
    if (this.title && this.title.content !== undefined) this.title.content = panelTitle(panel);
    if (this.count && this.count.content !== undefined) this.count.content = panelCount(panel, state);
    if (this.footer && this.footer.content !== undefined) this.footer.content = hintLine(panel);

    if (key === "activity") {
      if (this.activityHeader && this.activityHeader.content !== undefined) {
        const tools = turn?.tools.length ?? 0;
        this.activityHeader.content = tools ? `${tools} tool call${tools === 1 ? "" : "s"}` : "activity clear";
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
        this.diffPanel.update(session?.diff ?? null, state.ui.diffView ?? "unified");
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
      case "help":
        this.commands.update("");
        return;
      case "model":
        this.modelPanel.update(modelPanelContent(state));
        return;
      case "headless":
        this.headlessPanel.update(headlessPanelContent(state));
        return;
      case "acp":
        this.acpPanel.update(acpPanelContent());
        return;
      case "theme":
        this.themePanel.update(state);
        return;
      default:
        if (this.fallbackText && this.fallbackText.content !== undefined) {
          this.fallbackText.content = fallbackContent(panel, state);
        }
        return;
    }
  }

  hide(): void {
    this.setVisible(false);
  }

  setViewportWidth(width: number): void {
    const viewport = Number.isFinite(width) && width > 0 ? width : 120;
    const nextWidth = Math.max(42, Math.min(80, Math.floor(viewport * 0.5)));
    if (this.node && "width" in this.node) this.node.width = nextWidth;
    this.sessions.setViewportWidth(nextWidth);
  }

  isVisible(): boolean {
    return this.visible;
  }

  moveSelection(delta: -1 | 1): boolean {
    const list = this.activeList();
    if (!list) return false;
    return delta < 0 ? Boolean(list.moveUp?.()) : Boolean(list.moveDown?.());
  }

  commitSelection(): boolean {
    return Boolean(this.activeList()?.commit?.());
  }

  selectedValue(): string {
    return this.activeList()?.selectedValue?.() ?? "";
  }

  selectedCommandId(): CommandId | "" {
    return this.commands.selectedCommandId();
  }

  private setVisible(open: boolean): void {
    this.visible = open;
    if (this.node && "visible" in this.node) this.node.visible = open;
    if (this.node && "enableLayout" in this.node) this.node.enableLayout = open;
  }

  private activeList(): any {
    switch (this.activePanel) {
      case "sessions":
        return (this.sessions as any).select;
      case "context":
        return (this.context as any).files;
      case "replay":
        return (this.replay as any).select;
      case "eval":
        return (this.evalLab as any).select;
      case "skills":
        return (this.skills as any).select;
      case "review":
        return (this.failure as any).select;
      case "extensions":
        return (this.extensions as any).select;
      case "help":
        return (this.commands as any).list;
      default:
        return null;
    }
  }
}

function panelTitle(panel: string): string {
  const titles: Record<string, string> = {
    sessions: "sessions",
    context: "context",
    diff: "diff",
    usage: "usage",
    model: "model",
    replay: "replay",
    eval: "eval lab",
    skills: "skill forge",
    update: "update",
    review: "failure review",
    headless: "headless parity",
    acp: "acp bridge",
    theme: "theme",
    help: "commands",
    debug: "debug",
    settings: "settings",
    extensions: "extensions",
  };
  return titles[panel] ?? panel;
}

function panelCount(panel: string, state: AppState): string {
  let value = "";
  if (panel === "sessions") value = String(state.sessions.length);
  else if (panel === "context") value = String(state.workspaceFiles.length);
  else if (panel === "diff") value = String(state.activeSession?.diff?.paths.length ?? 0);
  else if (panel === "usage") value = String(state.activeSession?.usage.modelCalls ?? 0);
  else if (panel === "replay") value = String(state.replay?.events.length ?? 0);
  else if (panel === "eval") value = state.evalLab.status;
  else if (panel === "skills") value = String(state.skillForge.drafts.length);
  else if (panel === "extensions") value = String(state.extensions.length);
  else if (panel === "update") value = state.updatePanel.status;
  if (!value) return "";
  return ` ${glyphs.pillL} ${value} ${glyphs.pillR} `;
}

function hintLine(panel = ""): string {
  if (panel === "sessions") {
    return `${glyphs.kbdL}↑↓${glyphs.kbdR} nav   ${glyphs.kbdL}⏎${glyphs.kbdR} open   ${glyphs.kbdL}n${glyphs.kbdR} new`;
  }
  if (panel === "help") {
    return `${glyphs.kbdL}↑↓${glyphs.kbdR} nav   ${glyphs.kbdL}⏎${glyphs.kbdR} run   ${glyphs.kbdL}esc${glyphs.kbdR} close`;
  }
  if (panel === "theme") {
    return "semantic layer only · widgets unchanged";
  }
  return `${glyphs.kbdL}esc${glyphs.kbdR} close`;
}

function modelPanelContent(state: AppState): InfoPanelContent {
  return {
    eyebrow: "model state",
    rows: [
      {
        label: "provider",
        value: state.provider || "tinyagent",
        detail: "next turn",
        tone: "accent",
      },
      {
        label: "model",
        value: state.model || "default",
        detail: "generation model",
      },
      {
        label: "approval",
        value: state.approvalMode,
        detail: "tool gates",
      },
      {
        label: "session",
        value: state.sessionMode,
        detail: state.ui.showReasoning ? "reasoning shown" : "reasoning folded",
      },
    ],
  };
}

function headlessPanelContent(state: AppState): InfoPanelContent {
  const session = state.activeSession;
  const seq = state.replay?.cursorSeq || session?.lastSeq || 1;
  const run = `tinyagent run "<prompt>"`;
  const stream = `tinyagent run "<prompt>" --stream text`;
  const replay = "tinyagent replay <run-id>";
  const fork = `tinyagent fork <run-path> --at ${seq}`;
  const draftSkill = `tinyagent skills draft-from-run <run-path>`;
  const stdio = "tinyagent agent stdio --protocol tinyagent";
  const usage = session?.usage;
  const usageValue = usage
    ? `${usage.totalTokens} tok · ${usage.modelCalls} call${usage.modelCalls === 1 ? "" : "s"}`
    : "after first run";
  return {
    eyebrow: "headless parity",
    rows: [
      {
        label: "run",
        value: "start task",
        detail: run,
        tone: "accent",
      },
      {
        label: "stream",
        value: "watch progress",
        detail: stream,
      },
      {
        label: "replay",
        value: "review run",
        detail: replay,
      },
      {
        label: "fork",
        value: `from step ${seq}`,
        detail: fork,
      },
      {
        label: "eval",
        value: "run suite",
        detail: "tinyagent eval <suite-path>",
      },
      {
        label: "draft skill",
        value: "capture pattern",
        detail: draftSkill,
      },
      {
        label: "usage",
        value: usageValue,
        detail: "saved with run summary",
      },
      {
        label: "bridge",
        value: "connect clients",
        detail: stdio,
      },
    ],
    footer: "same trace · cli parity",
  };
}

function acpPanelContent(): InfoPanelContent {
  return {
    eyebrow: "acp bridge",
    rows: [
      {
        label: "bridge",
        value: "live session",
        detail: "app-connected turn stream",
        tone: "accent",
      },
      {
        label: "command",
        value: "app bridge",
        detail: "tinyagent agent stdio --protocol acp",
      },
      {
        label: "start",
        value: "open session",
        detail: "create conversation",
      },
      {
        label: "prompt",
        value: "stream turn",
        detail: "send user prompt",
      },
      {
        label: "cancel",
        value: "stop run",
        detail: "return control",
      },
      {
        label: "approval",
        value: "resolve tool",
        detail: "allow or deny",
      },
    ],
    footer: "same trace · app parity",
  };
}

function fallbackContent(panel: string, state: AppState): string {
  if (panel === "theme") {
    return [
      "theme",
      fallbackRow("palette", state.ui.theme, "active colors"),
      fallbackRow("spinner", state.ui.spinner, "motion preset"),
    ].join("\n");
  }
  return "";
}

function fallbackRow(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}
