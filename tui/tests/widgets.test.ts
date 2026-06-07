// Smoke tests for widget classes. Without a TTY/opentui we exercise the
// headless code paths and assert the widgets construct, update, and never
// throw on empty/partial state.

import { expect, test } from "bun:test";
import { ContextWidget } from "../src/ui/widgets/ContextWidget";
import { ApprovalModalWidget } from "../src/ui/widgets/ApprovalModal";
import { CommandMapWidget } from "../src/ui/widgets/CommandMapWidget";
import { DebugWidget } from "../src/ui/widgets/DebugWidget";
import { DiffWidget } from "../src/ui/widgets/DiffWidget";
import { EvalLabWidget } from "../src/ui/widgets/EvalLabWidget";
import { ExtensionsWidget } from "../src/ui/widgets/ExtensionsWidget";
import { FailureWidget } from "../src/ui/widgets/FailureWidget";
import { PlanBoardWidget } from "../src/ui/widgets/PlanBoardWidget";
import { RailWidget } from "../src/ui/widgets/Rail";
import { ReplayWidget } from "../src/ui/widgets/ReplayWidget";
import { SessionsWidget } from "../src/ui/widgets/SessionsWidget";
import { SkillForgeWidget } from "../src/ui/widgets/SkillForgeWidget";
import { SettingsWidget } from "../src/ui/widgets/SettingsWidget";
import { ToolTimelineWidget } from "../src/ui/widgets/ToolTimelineWidget";
import { TranscriptWidget } from "../src/ui/widgets/Transcript";
import { UpdateWidget } from "../src/ui/widgets/UpdateWidget";
import { UsageWidget } from "../src/ui/widgets/UsageWidget";
import { DividerWidget } from "../src/ui/widgets/Divider";
import { ContextMenuWidget } from "../src/ui/widgets/ContextMenu";
import { HistorySearchWidget } from "../src/ui/widgets/HistorySearch";
import { InfoPanelWidget } from "../src/ui/widgets/InfoPanelWidget";
import { PickerWidget } from "../src/ui/widgets/Picker";
import { ThemePanelWidget } from "../src/ui/widgets/ThemePanelWidget";
import { makePanelList } from "../src/ui/widgets/panelStyle";
import { resolveTheme } from "../src/ui/theme";
import { glyphs } from "../src/design/glyphs";
import { emptyState, createSession } from "../src/state/reducer";
import { candidatesForFile, candidatesForSkill, candidatesForSlash } from "../src/ui/mentions";
import { pickerCommands } from "../src/commands";
import { renderAcpPanel } from "../src/components/AcpPanel";
import { renderFailurePanel } from "../src/components/FailurePanel";
import { renderModelLab } from "../src/components/ModelLab";
import { renderSkillForge } from "../src/components/SkillForge";
import { renderDebugOverlay } from "../src/components/DebugOverlay";
import { renderUsagePanel } from "../src/components/UsagePanel";
import { renderEvalLab } from "../src/components/EvalLab";
import { renderTranscript } from "../src/components/Transcript";

const theme = resolveTheme("tiny-dark");

function nodeText(node: any): string {
  return `${node?.content ?? ""}${(node?.children ?? []).map(nodeText).join("")}`;
}

test("ToolTimelineWidget handles empty + populated state without throwing", () => {
  const widget = new ToolTimelineWidget(null, null, theme);
  widget.update([]);
  widget.update([
    { id: "1", tool: "shell", label: "shell ls", argsSummary: "ls", status: "done", output: "ok" },
  ]);
  expect(widget.node).toBeDefined();
});

test("ToolTimelineWidget keeps tool inputs in one-row lanes", () => {
  const widget = new ToolTimelineWidget(fakeOpentui(), null, theme);
  widget.update([
    { id: "1", tool: "read", label: "read", argsSummary: "Paper activity reference", status: "done", output: "" },
    { id: "2", tool: "plan.step", label: "patch activity panel", argsSummary: "PlanBoardWidget copy", status: "running", output: "" },
  ]);

  const rows = (widget as any).select.children;
  expect(rows[0].children).toHaveLength(1);
  expect(rows[1].children).toHaveLength(1);
  expect(nodeText(rows[0])).toContain("▍ ✓ read");
  expect(nodeText(rows[0])).toContain("Paper activity reference");
  expect(nodeText(rows[1])).toContain("⠋ patch");
  expect(nodeText(rows[1])).toContain("PlanBoardWidget copy");
  expect(widget.node.flexGrow).toBe(1);
});

test("ToolTimelineWidget keeps empty activity quiet", () => {
  const widget = new ToolTimelineWidget(fakeOpentui(), null, theme);
  widget.update([]);

  const select = (widget as any).select;
  const detail = (widget as any).detail;
  expect(select.visible).toBe(false);
  expect(select.enableLayout).toBe(false);
  expect(widget.node.flexGrow).toBe(0);
  expect(detail.content).toContain("tool calls");
  expect(detail.content).toContain("status        quiet");
  expect(detail.content).toContain("waiting for agent actions");
  expect(detail.content).not.toContain("none selected");
  expect(detail.content).not.toContain("none yet");
});

test("RailWidget keeps empty activity copy quiet", () => {
  const widget = new RailWidget(fakeOpentui(), null, theme);
  widget.update({
    ...emptyState(),
    ui: { ...emptyState().ui, activePanel: "activity" },
    activeSession: { ...createSession("conv_activity"), turns: [] },
  });

  expect((widget as any).activityHeader.content).toBe("activity clear");
  const detail = (widget as any).tools.detail;
  expect(detail.content).toContain("status        quiet");
  expect(detail.content).toContain("waiting for agent actions");
  expect(detail.content).not.toContain("none yet");
});

test("PlanBoardWidget reflects sessionMode", () => {
  const widget = new PlanBoardWidget(fakeOpentui(), null, theme);
  widget.update(emptyState());
  expect((widget as any).title.content).toBe("session mode");
  expect((widget as any).body.content).toContain("mode          build");
  expect((widget as any).body.content).toContain("write tools available");
  expect((widget as any).body.content).not.toContain("/plan");

  widget.update({ ...emptyState(), sessionMode: "plan" });
  expect((widget as any).title.content).toBe("session mode");
  expect((widget as any).body.content).toContain("mode          plan");
  expect((widget as any).body.content).toContain("write tools locked");
  expect((widget as any).body.content).not.toContain("/build");
  expect((widget as any).title.content).not.toContain("PLAN MODE ACTIVE");
  expect((widget as any).title.content).not.toContain("Build mode");
  expect(widget.node).toBeDefined();
});

test("PlanBoardWidget renders plan-step status with shared glyphs", () => {
  const widget = new PlanBoardWidget(fakeOpentui(), null, theme);
  const planState = {
    ...emptyState(),
    sessionMode: "plan",
    activeSession: {
      ...createSession("conv_plan"),
      turns: [
        {
          id: "turn-plan",
          runId: "run-plan",
          user: "review plan",
          assistant: "",
          reasoning: [],
          tools: [
            { id: "plan-1", tool: "plan", label: "inspect Paper", argsSummary: "", status: "done", output: "" },
            { id: "plan-2", tool: "plan.step", label: "patch activity panel", argsSummary: "", status: "running", output: "" },
          ],
          phase: "thinking",
          startedAt: "20:48",
          completedAt: "",
        },
      ],
    },
  };
  widget.update(planState);
  widget.update(planState);

  const steps = (widget as any).steps.children.map((child: any) => child.content);
  expect(steps).toEqual(["✓ inspect Paper", "⠋ patch activity panel"]);
});

test("SessionsWidget tolerates an empty list", () => {
  const widget = new SessionsWidget(null, null, theme);
  widget.update([]);
  widget.update([
    {
      conversation_id: "conv_a",
      title: "alpha",
      status: "open",
      active_turn_id: null,
      created_at: "",
      updated_at: "",
      workspace: ".",
      turn_count: 2,
    },
  ]);
  expect(widget.node).toBeDefined();
});

test("SessionsWidget renders Paper-style session metadata lanes", () => {
  const widget = new SessionsWidget(fakeOpentui(), null, theme);
  widget.update([
    {
      conversation_id: "conv_design",
      title: "design tokens · TUI",
      status: "active",
      active_turn_id: null,
      created_at: "",
      updated_at: "2m ago",
      workspace: "tinyagent",
      turn_count: 14,
      model: "gpt-5",
      tokens: 4200,
    } as any,
    {
      conversation_id: "conv_review",
      title: "review-gated learning",
      status: "done",
      active_turn_id: null,
      created_at: "",
      updated_at: "2h ago",
      workspace: "tinyagent",
      turn_count: 27,
      model: "gpt-5",
      tokens: 11_400,
    } as any,
  ]);

  const select = (widget as any).select;
  expect(select.children[0].children[0].content).toContain("▍ design tokens · TUI");
  expect(select.children[0].children[0].content).toContain("active");
  expect(select.children[0].children[1].content).toBe("  gpt-5 · 14 turns · 4.2k tok · 2m ago");
  expect(select.moveDown()).toBe(true);
  expect(select.children[1].children[0].content).toContain("▍ review-gated learning");
  expect(select.children[1].children[1].content).toBe("  gpt-5 · 27 turns · 11.4k tok · 2h ago");
});

test("SessionsWidget compacts selected metadata for the narrow rail", () => {
  const widget = new SessionsWidget(fakeOpentui(), null, theme);
  widget.setViewportWidth(42);
  widget.update([
    {
      conversation_id: "conv_design",
      title: "design tokens · TUI",
      status: "active",
      active_turn_id: null,
      created_at: "",
      updated_at: "2m ago",
      workspace: "tinyagent",
      turn_count: 14,
      model: "gpt-5",
      tokens: 4200,
    } as any,
  ]);

  const select = (widget as any).select;
  expect(select.children[0].children[0].content).toContain("active");
  expect(select.children[0].children[1].content).toBe("  gpt-5 · 14 turns · 4.2k tok");
  expect(select.children[0].children[1].content).not.toContain("2m ago");
  expect(Array.from(select.children[0].children[0].content).length).toBeLessThanOrEqual(34);
  expect(Array.from(select.children[0].children[1].content).length).toBeLessThanOrEqual(34);
});

test("RailWidget keeps sessions footer aligned with overlay controls", () => {
  const widget = new RailWidget(fakeOpentui(), null, theme);
  widget.setViewportWidth(120);
  widget.update({
    ...emptyState(),
    ui: { ...emptyState().ui, activePanel: "sessions" },
    sessions: [
      {
        conversation_id: "conv_design",
        title: "design tokens · TUI",
        status: "active",
        active_turn_id: null,
        created_at: "",
        updated_at: "2m ago",
        workspace: "tinyagent",
        turn_count: 14,
        model: "gpt-5",
        tokens: 4200,
      } as any,
    ],
  });

  const footer = (widget as any).footer.content;
  expect((widget as any).node.width).toBe(60);
  expect(footer).toContain("⌜↑↓⌟ nav");
  expect(footer).toContain("⌜⏎⌟ open");
  expect(footer).toContain("⌜n⌟ new");
  expect(footer).not.toContain("⌜esc⌟ close");
  widget.setViewportWidth(80);
  expect((widget as any).node.width).toBe(42);
  widget.setViewportWidth(240);
  expect((widget as any).node.width).toBe(80);
});

test("ApprovalModalWidget routes Escape to a safe deny decision", () => {
  const widget = new ApprovalModalWidget(null, null, theme);
  const decisions: Array<[string, string]> = [];
  widget.setOnDecide((decision, id) => decisions.push([decision, id]));
  widget.setApproval({
    approval_id: "approval_escape",
    tool_name: "shell",
    action_kind: "run-command",
    risk: "high",
    command: "rm -rf node_modules",
    args_preview: "rm -rf node_modules",
  } as any);
  widget.node.onKeyDown({ name: "escape" });
  expect(decisions).toEqual([["denied", "approval_escape"]]);
});

test("ApprovalModalWidget follows the Paper approval copy", () => {
  const widget = new ApprovalModalWidget(fakeOpentui(), null, theme);
  widget.setApproval({
    approval_id: "approval_copy",
    tool_name: "shell",
    action_kind: "run-command",
    risk: "high",
    command: "rm -rf node_modules",
    args_preview: "rm -rf node_modules",
    cwd: "/Users/kristian/work/dev/tinyagent",
    turn_id: "turn 7",
  } as any);

  const modal = widget as any;
  expect(modal.modal.width).toBe(60);
  expect(modal.modal.paddingX).toBe(3);
  expect(modal.commandLine.content).toBe("rm -rf node_modules");
  expect(modal.riskLine.content).toBe("requested by: agent · turn 7");
  expect(modal.keyAllowSession.content).toContain("allow for session");
  expect(modal.keyAllowOnce.fg).toBe(theme.text);
  expect(modal.keyAllowSession.fg).toBe(theme.text);
  expect(modal.keyDeny.fg).toBe(theme.text);
  expect(modal.keyEdit.content).toContain("edit command");
  expect(modal.hint.content).toContain("esc");
  expect(modal.hint.content).toContain("dismisses");
});

test("ApprovalModalWidget does not expose edit as an active decision", () => {
  const widget = new ApprovalModalWidget(null, null, theme);
  const decisions: Array<[string, string]> = [];
  widget.setOnDecide((decision, id) => decisions.push([decision, id]));
  widget.setApproval({
    approval_id: "approval_edit_future",
    tool_name: "shell",
    action_kind: "run-command",
    risk: "high",
    command: "rm -rf node_modules",
    args_preview: "rm -rf node_modules",
  } as any);

  widget.node.onKeyDown({ name: "e" });
  expect(decisions).toEqual([]);
});

test("ReplayWidget tolerates null replay", () => {
  const widget = new ReplayWidget(null, null, theme);
  widget.update(null);
  expect((widget as any).header.content).toContain("status         empty");
  expect((widget as any).header.content).not.toContain("No replay loaded.");
  widget.update({
    runId: "run_x",
    events: [],
    cursorSeq: 0,
    rawEvent: null,
    projected: null,
    forkDir: "",
    replayMs: 0,
  });
  expect((widget as any).header.content).toContain("no run loaded");
  expect(widget.node).toBeDefined();
});

test("ReplayWidget selects the cursor event with one active row marker", () => {
  const widget = new ReplayWidget(fakeOpentui(), null, theme);
  widget.update({
    runId: "run1",
    cursorSeq: 2,
    replayMs: 1.2,
    forkDir: "",
    events: [
      { seq: 1, type: "run.started", data: {} },
      { seq: 2, type: "model.text.delta", data: {} },
    ],
    rawEvent: null,
    projected: null,
  });

  const select = (widget as any).select;
  expect((widget as any).header.content).toContain("run            run1");
  expect((widget as any).header.content).toContain("saved trace");
  expect(select.children[1].children[0].content).toContain("▍ assistant delta");
  expect(select.children[1].children[1].content).toContain("assistant text");
  expect(select.children[1].children[1].content).not.toContain("model.text.delta");
  expect(select.children[1].children[0].content.endsWith("step 2")).toBe(true);
  expect(select.children[1].children[0].content).not.toContain("0002");
  expect(select.children[0].children[0].content).not.toContain(">");
});

test("ReplayWidget keeps raw run and fork ids out of primary lanes", () => {
  const widget = new ReplayWidget(fakeOpentui(), null, theme);
  widget.update({
    runId: "run_overlay_refactor",
    cursorSeq: 1,
    replayMs: 5.7,
    forkDir: "/private/tmp/tinyagent/fork-0004",
    events: [{ seq: 1, type: "tool.execution.completed", data: { tool: "read" } }],
    rawEvent: { seq: 1, type: "tool.execution.completed", data: { tool: "read", output: "ok" } } as any,
    projected: { phase: "streaming", turns: 1, tools: 1, assistantPreview: "done" },
  });

  const header = (widget as any).header.content;
  expect(header).toContain("run            overlay refactor");
  expect(header).toContain("saved trace");
  expect(header).toContain("timeline       1 step");
  expect(header).toContain("cursor 1 · replay 5.7ms");
  expect(header).toContain("fork           workspace copy");
  expect(header).toContain("temporary workspace");
  expect(header).not.toContain("run_overlay_refactor");
  expect(header).not.toContain("fork 0004");
  expect(header).not.toContain("/private/tmp/tinyagent/fork-0004");
  expect(header).not.toContain("projected");
  expect(header).not.toContain("Run: run_overlay_refactor");
  expect(header).not.toContain("Fork: /private/tmp/tinyagent/fork-0004");
  expect((widget as any).select.children[0].children[0].content).toContain("▍ tool completed");
  expect((widget as any).select.children[0].children[1].content).toContain("read · output captured");
  const detail = (widget as any).eventDetail.content;
  expect(detail).toContain("selected step");
  expect(detail).toContain("step           1");
  expect(detail).toContain("read · output captured");
  expect(detail).toContain("tool           read");
  expect(detail).toContain("output         ok");
  expect(detail).not.toContain("event detail");
  expect(detail).not.toContain("event          0001");
  expect(detail).not.toContain("0001");
  expect(detail).not.toContain("tool.execution.completed");
  expect(detail).not.toContain("event data");
  expect(detail).not.toContain('"output"');
  const projection = (widget as any).projection.content;
  expect(projection).toContain("turn preview");
  expect(projection).toContain("phase          streaming");
  expect(projection).toContain("1 turn · 1 tool · 5.7ms replay");
  expect(projection).toContain("assistant      response preview");
  expect(projection).toContain("done");
  expect(projection).not.toContain("run state");
  expect(projection).not.toContain("projection");
});

test("FailureWidget tolerates null + populated explanation", () => {
  const widget = new FailureWidget(null, null, theme);
  widget.update(null);
  widget.update({
    source: "model",
    lastSuccessfulEvent: "2 model.call.started",
    failedEvent: "3 model.call.failed",
    recoveryActions: ["one", "two"],
  });
  expect(widget.node).toBeDefined();
});

test("FailureWidget keeps recovery actions readable", () => {
  const widget = new FailureWidget(fakeOpentui(), null, theme);
  widget.update({
    source: "model",
    lastSuccessfulEvent: "14 tool.execution.completed",
    failedEvent: "15 model.call.failed",
    recoveryActions: [
      "Inspect raw failed event with /replay.",
      "Project state before failure with /rewind 14.",
      "Retry with a smaller prompt bundle.",
    ],
  });

  const rows = widget.node.children[0].children[1];
  expect(rows.children[0].children[0].children[1].content).toBe("source");
  expect(rows.children[0].children[0].children[2].content).toBe("model");
  expect(rows.children[0].children[1].content).toBe("  stopped turn");
  expect(rows.children[0].children[1].content).not.toContain("failure source");
  expect(rows.children[1].children[0].children[1].content).toBe("last ok");
  expect(rows.children[1].children[0].children[2].content).toBe("step 14");
  expect(rows.children[1].children[1].content).toBe("  tool completed · safe checkpoint");
  expect(rows.children[2].children[0].children[1].content).toBe("failed");
  expect(rows.children[2].children[0].children[2].content).toBe("step 15");
  expect(rows.children[2].children[1].content).toBe("  model failed · replay target");

  const select = (widget as any).select;
  expect(select.children[0].children[0].content).toContain("▍ inspect failure");
  expect(select.children[0].children[0].content).toContain("/replay");
  expect(select.children[1].children[0].content).toContain("rewind before failure");
  expect(select.children[1].children[0].content).toContain("/rewind 14");
  expect(select.children[2].children[0].content).toContain("retry compact prompt");
  expect(select.children[0].children[1].content.trim()).toBe("open replay");
  expect(select.children[1].children[1].content.trim()).toBe("step 14");
  expect(select.children[2].children[1].content.trim()).toBe("smaller bundle");
});

test("renderFailurePanel uses terse recovery copy", () => {
  const output = renderFailurePanel({
    source: "model",
    lastSuccessfulEvent: "14 tool.execution.completed",
    failedEvent: "15 model.call.failed",
    recoveryActions: [
      "Inspect raw failed event with /replay.",
      "Project state before failure with /rewind 14.",
      "Retry with a smaller prompt bundle.",
    ],
  });

  expect(output).toContain("failure review");
  expect(output).toContain("source        model");
  expect(output).toContain("stopped turn");
  expect(output).toContain("last ok");
  expect(output).toContain("last ok       step 14");
  expect(output).toContain("tool completed · safe checkpoint");
  expect(output).toContain("failed        step 15");
  expect(output).toContain("model failed · replay target");
  expect(output).toContain("safe checkpoint");
  expect(output).toContain("replay target");
  expect(output).toContain("inspect       /replay");
  expect(output).toContain("rewind        /rewind 14");
  expect(output).toContain("retry         compact prompt");
  expect(output).not.toContain("failure origin");
  expect(output).not.toContain("failure source");
  expect(output).not.toContain("inspect raw event data");
  expect(output).not.toContain("event 14");
  expect(output).not.toContain("event 15");
  expect(output).not.toContain("recovery option");
  expect(output).not.toContain("tool.execution.completed");
  expect(output).not.toContain("model.call.failed");
});

test("ExtensionsWidget keeps extension metadata in readable lanes", () => {
  const widget = new ExtensionsWidget(fakeOpentui(), null, theme);
  widget.update([
    {
      name: "mcp",
      kind: "mcp",
      servers: ["filesystem", "linear", "paper"],
      enabled: true,
      description: "Connected tool servers available to the local agent runtime.",
    },
    {
      name: "lsp",
      kind: "lsp",
      servers: ["typescript", "python"],
      enabled: true,
      description: "Language servers used for hover, symbols, and diagnostics.",
    },
    {
      name: "product_runtime",
      kind: "feature",
      enabled: false,
      description: "Product runtime hooks.",
    },
  ]);

  const select = (widget as any).select;
  expect(select.children[0].children[0].content).toContain("▍ mcp");
  expect(select.children[0].children[0].content).toContain("3 servers");
  expect(select.children[0].children[1].content).toBe("  servers: filesystem, linear, paper");
  expect(select.children[1].children[0].content).toContain("2 servers");
  expect(select.children[1].children[1].content).toBe("  servers: typescript, python");
  expect(select.children[2].children[0].content).toContain("app hooks");
  expect(select.children[2].children[0].content).toContain("off");
  expect(select.children[2].children[1].content).toBe("  lifecycle hooks");
  expect(select.children[0].children[0].content).not.toContain("▤");
  expect(select.children[1].children[0].content).not.toContain("⌘");
  expect(select.children[2].children[0].content).not.toContain("✦");
  expect(select.children[0].children[0].content).not.toContain("mcp ·");
  expect(select.children[1].children[0].content).not.toContain("lsp ·");
  expect(select.children[2].children[0].content).not.toContain("hook ·");
  expect(select.children[2].children[0].content).not.toContain("product_runtime");
  expect(select.children[2].children[0].content).not.toContain("product runtime");
  expect(select.children[0].children[1].content).not.toContain("Connected tool servers");
  expect(select.children[1].children[1].content).not.toContain("Language servers used");
  expect(select.children[2].children[1].content).not.toContain("Product runtime hooks");
  expect(select.children[2].children[1].content).not.toContain("runtime hooks");
  const detail = (widget as any).detail.node.children[1];
  expect(detail.children[0].children[1].content).toBe("  enabled");
  expect(detail.children[1].children[1].content).toBe("  3 servers");
  expect(detail.children[0].children[1].content).not.toContain("mcp ·");
});

test("ExtensionsWidget keeps unselected fallback quiet", () => {
  const widget = new ExtensionsWidget(fakeOpentui(), null, theme);
  (widget as any).renderDetail(undefined);

  const detail = (widget as any).detail.node.children[1];
  expect(detail.children[0].children[0].children[2].content).toBe("quiet");
  expect(detail.children[0].children[1].content).toBe("  choose an extension row");
  expect(detail.children[0].children[0].children[2].content).not.toBe("none selected");
});

test("DiffWidget gives patch content a compact summary lane", () => {
  const widget = new DiffWidget(fakeOpentui(), null, theme);
  widget.update(
    {
      paths: ["tui/src/ui/widgets/Rail.ts", "tui/src/ui/widgets/panelStyle.ts"],
      truncated: false,
      text: [
        "diff --git a/tui/src/ui/widgets/Rail.ts b/tui/src/ui/widgets/Rail.ts",
        "--- a/tui/src/ui/widgets/Rail.ts",
        "+++ b/tui/src/ui/widgets/Rail.ts",
        "@@ -83,2 +83,2 @@",
        "-      backgroundColor: theme.surface,",
        "+      backgroundColor: theme.surfaceOverlay,",
        "diff --git a/tui/src/ui/widgets/panelStyle.ts b/tui/src/ui/widgets/panelStyle.ts",
        "--- /dev/null",
        "+++ b/tui/src/ui/widgets/panelStyle.ts",
        "@@ -0,0 +1,2 @@",
        "+export const panel = true;",
        "+export const quiet = true;",
      ].join("\n"),
    },
    "unified",
  );

  const summary = (widget as any).summary;
  const rows = summary.node.children[1].children;
  expect(summary.node.children[0].content).toBe("diff summary");
  expect(rows[0].children[0].children[1].content).toBe("files");
  expect(rows[0].children[0].children[2].content).toBe("2 changed files");
  expect(rows[0].children[1].content).toBe("  Rail.ts · panelStyle.ts");
  expect(rows[1].children[0].children[1].content).toBe("changes");
  expect(rows[1].children[0].children[2].content).toBe(`+3 ${glyphs.minus}1`);
  expect(rows[1].children[1].content).toBe("  unified · full patch");
  expect((widget as any).diffNode.content).toContain("backgroundColor: theme.surfaceOverlay");
  expect((widget as any).diffNode.content).not.toContain("Files:");
});

function skillForgeFixture() {
  return {
    status: "ready",
    selectedDraftId: "draft_overlay_review",
    lastAction: "show draft_overlay_review",
    error: "",
    drafts: [
      {
        draft_id: "draft_overlay_review",
        name: "overlay-review",
        path: "skills/overlay-review/SKILL.md",
        status: "draft",
        source_run_id: "run_overlay_refactor",
        created_at: "2026-05-25T18:45:00Z",
      },
      {
        draft_id: "draft_visual_check",
        name: "visual-check",
        path: "skills/visual-check/SKILL.md",
        status: "ready",
        source_run_id: "run_snapshots",
        created_at: "2026-05-25T18:10:00Z",
      },
    ],
    markdown: [
      "# overlay-review",
      "",
      "For TUI overlay panel changes.",
      "",
      "- inspect Paper",
      "- update a focused surface",
      "- capture snapshots before calling the work done",
    ].join("\n"),
  };
}

test("SkillForgeWidget keeps draft rows human-readable", () => {
  const widget = new SkillForgeWidget(fakeOpentui(), null, theme);
  widget.update(skillForgeFixture());

  const select = (widget as any).select;
  expect(select.children[0].children[0].content).toContain("▍ overlay-review");
  expect(select.children[0].children[0].content).toContain("draft");
  expect(select.children[0].children[1].content).toBe("  skills/overlay-review/SKILL.md · overlay refactor");
  expect(select.children[0].children[1].content).not.toContain("draft_overlay_review");
  expect(select.children[0].children[1].content).not.toContain("run_overlay_refact…");
  expect((widget as any).header.node.children[1].children[1].children[0].children[1].content).toBe("draft");
  expect((widget as any).header.node.children[1].children[1].children[1].content).toBe("  skills/overlay-review/SKILL.md");
  expect((widget as any).header.node.children[1].children[1].children[1].content).not.toContain("show ");
  expect((widget as any).preview.content).toContain("draft preview");
  expect((widget as any).preview.content).not.toContain("selected draft");
  expect((widget as any).preview.content).toContain("purpose       TUI overlay panel changes");
  expect((widget as any).preview.content).toContain("draft intent");
  expect((widget as any).preview.content).toContain("step 1        inspect Paper");
  expect((widget as any).preview.content).toContain("1 of 3");
  expect((widget as any).preview.content).not.toContain("from skill file");
  expect((widget as any).preview.content).not.toContain("workflow");
  expect((widget as any).preview.content).not.toContain("# overlay-review");
  expect((widget as any).preview.content).not.toContain("- inspect Paper");
});

test("renderSkillForge uses compact draft preview", () => {
  const output = renderSkillForge(skillForgeFixture());
  expect(output).toContain("draft         overlay-review");
  expect(output).toContain("draft preview");
  expect(output).not.toContain("selected      overlay-review");
  expect(output).not.toContain("selected draft");
  expect(output).toContain("purpose       TUI overlay panel changes");
  expect(output).toContain("draft intent");
  expect(output).toContain("step 3        capture snapshots");
  expect(output).toContain("3 of 3");
  expect(output).not.toContain("draft_overlay_review");
  expect(output).not.toContain("from skill file");
  expect(output).not.toContain("workflow");
  expect(output).not.toContain("# overlay-review");
  expect(output).not.toContain("- capture snapshots");
});

test("renderSkillForge keeps unnamed draft ids out of visible rows", () => {
  const output = renderSkillForge({
    ...skillForgeFixture(),
    selectedDraftId: "draft_run_1",
    drafts: [
      {
        draft_id: "draft_run_1",
        name: "",
        path: "skills/run-1/SKILL.md",
        status: "draft",
        source_run_id: "run_1",
        created_at: "2026-05-25T18:45:00Z",
      },
    ],
    markdown: "",
  });

  expect(output).toContain("run 1");
  expect(output).toContain("preview       pending");
  expect(output).not.toContain("draft_run_1");
});

test("EvalLabWidget keeps output paths out of the value lane", () => {
  const widget = new EvalLabWidget(fakeOpentui(), null, theme);
  widget.update({
    status: "completed",
    suitePath: "evals/tui-overlay.yaml",
    outputDir: ".tinyagent/evals/overlay-20260525",
    command: "tinyagent eval run evals/tui-overlay.yaml",
    error: "",
    results: [
      { case_id: "slash-picker", success: true, status: "passed", model_call_count: 1, tool_call_count: 0 },
      {
        case_id: "compact-80col",
        success: false,
        status: "failed",
        failure_reason: "footer clipped at 80 columns",
        model_call_count: 1,
        tool_call_count: 0,
      },
    ],
    report: "overlay visual eval\nneeds review: compact-80col footer clipping\nnext step · tighten footer hint spacing before release",
  });

  const rows = (widget as any).header.node.children[1];
  const suite = rows.children[1];
  const output = rows.children[2];
  expect(suite.children[0].children[2].content).toBe("evals/tui-overlay.yaml");
  expect(suite.children[1].content).toBe("  snapshot gate");
  expect(suite.children[1].content).not.toContain("tinyagent eval run");
  expect(output.children[0].children[2].content).toBe("eval artifacts");
  expect(output.children[1].content).toBe("  .tinyagent/evals/overlay-20260525");
  expect(output.children[0].children[2].content).not.toContain(".tinyagent");
  expect((widget as any).footer.content).toBe("needs review · compact-80col · footer clipped");
  expect((widget as any).footer.content).not.toContain("at 80 columns");
  expect((widget as any).footer.content).not.toContain("next step");
  expect((widget as any).footer.content).not.toContain("overlay visual eval");
});

test("renderEvalLab keeps suite copy product-facing", () => {
  const output = renderEvalLab({
    status: "completed",
    suitePath: "evals/tui-overlay.yaml",
    outputDir: ".tinyagent/evals/overlay-20260525",
    command: "tinyagent eval run evals/tui-overlay.yaml",
    error: "",
    results: [
      { case_id: "slash-picker", success: true, status: "passed", model_call_count: 1, tool_call_count: 0 },
      { case_id: "compact-80col", success: false, status: "failed", failure_reason: "footer clipped at 80 columns" },
    ],
    report: "overlay visual eval\nnext step · tighten footer hint spacing before release",
  });

  expect(output).toContain("status        completed");
  expect(output).toContain("1 / 2 passing");
  expect(output).toContain("suite         evals/tui-overlay.yaml");
  expect(output).toContain("snapshot gate");
  expect(output).not.toContain("tinyagent eval run");
  expect(output).not.toContain("suite path");
});

test("EvalLab/Skill/Update/Context/Usage/Debug widgets accept empty state", () => {
  const evalLab = new EvalLabWidget(null, null, theme);
  evalLab.update(emptyState().evalLab);
  const skills = new SkillForgeWidget(null, null, theme);
  skills.update(emptyState().skillForge);
  const update = new UpdateWidget(null, null, theme);
  update.update(emptyState().updatePanel);
  const context = new ContextWidget(null, null, theme);
  context.update(null, [], null);
  const usage = new UsageWidget(null, null, theme);
  usage.update(emptyState().activeSession?.usage ?? { inputTokens: 0, outputTokens: 0, totalTokens: 0, modelCalls: 0, latencyMs: 0 });
  const debug = new DebugWidget(null, null, theme);
  debug.update({ ...emptyState(), activeSession: createSession("conv") });
  expect(evalLab.node && skills.node && update.node && context.node && usage.node && debug.node).toBeTruthy();
});

test("UsageWidget keeps latency as a compact state lane", () => {
  const widget = new UsageWidget(fakeOpentui(), null, theme);
  widget.update({ inputTokens: 48_212, outputTokens: 9_408, totalTokens: 57_620, modelCalls: 11, latencyMs: 18_740 });

  const rows = (widget as any).panel.node.children[1];
  expect(rows.children[2].children[0].children[1].content).toBe("latency");
  expect(rows.children[2].children[0].children[2].content).toBe("18.7s");
  expect(rows.children[2].children[1].content).toBe("  end to end");
  expect(rows.children[2].children[0].children[2].content).not.toContain("18,740 ms");
  expect(rows.children[2].children[1].content).not.toContain("seconds");
});

test("renderUsagePanel keeps latency copy compact", () => {
  const output = renderUsagePanel({ inputTokens: 48_212, outputTokens: 9_408, totalTokens: 57_620, modelCalls: 11, latencyMs: 18_740 });
  expect(output).toContain("latency       18.7s");
  expect(output).toContain("end to end");
  expect(output).not.toContain("18,740 ms");
  expect(output).not.toContain("seconds end to end");
});

test("DebugWidget keeps runtime diagnostics terse", () => {
  const widget = new DebugWidget(fakeOpentui(), null, theme);
  const state = {
    ...emptyState(),
    provider: "openai",
    model: "gpt-5",
    phase: "streaming",
    approvalMode: "on-request",
    sessionMode: "plan",
    ui: { ...emptyState().ui, activePanel: "debug", paletteOpen: false, diffView: "unified", showReasoning: false },
    activeSession: { ...createSession("conv"), lastSeq: 88 },
  };
  state.activeSession.eventsBySeq = new Map([
    [86, { seq: 86, type: "tool.execution.started", data: {} } as any],
    [87, { seq: 87, type: "tool.execution.completed", data: {} } as any],
    [88, { seq: 88, type: "model.text.delta", data: {} } as any],
  ]);
  widget.update(state);

  const rows = (widget as any).panel.node.children[1];
  expect(rows.children[0].children[1].content).toBe("  approval on-request · plan session");
  expect(rows.children[1].children[1].content).toBe("  next turn");
  expect(rows.children[2].children[0].children[1].content).toBe("theme");
  expect(rows.children[2].children[0].children[2].content).toBe("paper-dark");
  expect(rows.children[2].children[1].content).toBe("  semantic layer only · widgets unchanged");
  expect(rows.children[3].children[0].children[1].content).toBe("activity");
  expect(rows.children[3].children[0].children[2].content).toBe("3 steps");
  expect(rows.children[3].children[1].content).toBe("  latest step 88 · 0 turns");
  expect(rows.children[4].children[0].children[2].content).toBe("0 steps");
  expect(rows.children[4].children[1].content).toBe("  0.0 ms timeline");
  expect(rows.children[5].children[0].children[1].content).toBe("surface");
  expect(rows.children[5].children[0].children[2].content).toBe("debug overlay");
  expect(rows.children[5].children[1].content).toBe("  right sheet · diff unified");
  expect(rows.children[6].children[0].children[2].content).toBe("folded");
  expect(rows.children[6].children[1].content).toBe("  transcript fold");
  expect(rows.children[5].children[0].children[1].content).not.toBe("overlay");
  expect(rows.children[5].children[0].children[2].content).not.toBe("open");
  expect(rows.children[3].children[0].children[1].content).not.toBe("events");
  expect(rows.children[3].children[1].content).not.toContain("last seq");
  expect(rows.children[4].children[0].children[2].content).not.toContain("events");
  expect(rows.children[5].children[1].content).not.toContain("palette closed");
  expect(rows.children[4].children[1].content).not.toContain("projection");
  expect(rows.children[6].children[1].content).not.toContain("projection");
  expect(rows.children[1].children[1].content).not.toContain("debug panel");
});

test("renderDebugOverlay uses compact state rows", () => {
  const state = {
    ...emptyState(),
    provider: "openai",
    model: "gpt-5",
    phase: "streaming",
    approvalMode: "on-request",
    sessionMode: "plan",
    ui: { ...emptyState().ui, activePanel: "debug", paletteOpen: false, diffView: "unified", showReasoning: false },
    activeSession: { ...createSession("conv"), lastSeq: 88 },
  };
  state.activeSession.eventsBySeq = new Map([[88, { seq: 88, type: "model.text.delta", data: {} } as any]]);
  const output = renderDebugOverlay(state);
  expect(output).toContain("debug");
  expect(output).toContain("phase         streaming");
  expect(output).toContain("approval on-request · plan session");
  expect(output).toContain("model         openai · gpt-5");
  expect(output).toContain("theme         paper-dark");
  expect(output).toContain("semantic layer only · widgets unchanged");
  expect(output).toContain("activity      1 step");
  expect(output).toContain("latest step 88 · 0 turns");
  expect(output).toContain("replay        0 steps");
  expect(output).toContain("0.0 ms timeline");
  expect(output).toContain("surface       debug overlay");
  expect(output).toContain("right sheet · diff unified");
  expect(output).toContain("reasoning     folded");
  expect(output).toContain("transcript fold");
  expect(output).not.toContain("last seq");
  expect(output).not.toContain("replay        0 events");
  expect(output).not.toContain("debug rail");
  expect(output).not.toContain("right overlay");
  expect(output).not.toContain("overlay       open");
  expect(output).not.toContain("palette closed");
  expect(output).not.toContain("phase=");
  expect(output).not.toContain("replayMs=");
  expect(output).not.toContain("projection");
  expect(output).not.toContain("debug panel");
});

test("ContextWidget keeps git status in the right metadata lane", () => {
  const widget = new ContextWidget(fakeOpentui(), null, theme);
  widget.update(
    { name: "tinyagent", root: "/Users/k/work/dev/tinyagent" },
    ["tui/src/ui/widgets/ContextWidget.ts", "tui/src/ui/widgets/panelStyle.ts"],
    {
      isRepo: true,
      clean: false,
      branch: "tui-paper-overlay",
      ahead: 2,
      behind: 0,
      files: [
        { path: "tui/src/ui/widgets/ContextWidget.ts", status: "modified" },
        { path: "tui/src/ui/widgets/panelStyle.ts", status: "added" },
      ],
      diff: "",
      diffTruncated: false,
    },
  );

  const summary = (widget as any).summary.node.children[1];
  expect(summary.children[0].children[1].content).toBe("  ~/work/dev/tinyagent");
  expect(summary.children[2].children[1].content).toBe("  file mentions");
  expect(summary.children[0].children[1].content).not.toContain("/Users/k");
  expect(summary.children[2].children[1].content).not.toContain("workspace mention index");
  const files = (widget as any).files;
  expect(files.children[0].children[0].content).toContain("▍ tui/src/ui/widgets/ContextWidget.ts");
  expect(files.children[0].children[0].content.endsWith("modified")).toBe(true);
  expect(files.children[0].children[0].content).not.toContain("▍ M ");
  expect(files.children[1].children[0].content.endsWith("added")).toBe(true);
});

test("DividerWidget tracks width and notifies listener", () => {
  const divider = new DividerWidget(null, null, theme);
  let received = 0;
  divider.setListener((width) => {
    received = width;
  });
  divider.setWidth(64);
  expect(received).toBe(64);
  expect(divider.getWidth()).toBe(64);
});

test("ContextMenuWidget shows and hides without errors", () => {
  const menu = new ContextMenuWidget(null, null, theme);
  expect(menu.isVisible()).toBe(false);
  menu.showAt(2, 3, [{ label: "Copy", value: "copy" }], () => {});
  // headless node mocks `visible` writes silently
  menu.hide();
});

test("ContextMenuWidget keeps action metadata in one row", () => {
  const menu = new ContextMenuWidget(fakeOpentui(), null, theme);
  menu.showAt(
    2,
    3,
    [
      { label: "Copy last reply", description: "Copy assistant text", value: "copy-last" },
      { label: "Copy conversation", description: "Copy all turns", value: "copy-conv" },
      { label: "Stop run", description: "Cancel active run", value: "stop-run" },
    ],
    () => {},
  );

  const select = (menu as any).select;
  expect(select.children[0].children).toHaveLength(1);
  expect(select.children[0].children[0].content).toContain("▍ Copy last reply");
  expect(select.children[0].children[0].content.endsWith("assistant text")).toBe(true);
  expect(select.children[1].children[0].content.endsWith("all turns")).toBe(true);
  expect(select.children[2].children[0].content.endsWith("cancel run")).toBe(true);
  const hint = (menu as any).node.children[2].children[0].content;
  expect(hint).toBe(`${glyphs.kbdL}↑↓${glyphs.kbdR} move   ${glyphs.kbdL}⏎${glyphs.kbdR} choose   ${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(hint).toContain(`${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(hint).not.toContain(" · ");
  expect(hint).not.toContain(`${glyphs.kbdL}esc${glyphs.kbdR} close`);
  expect(hint).not.toContain(`${glyphs.kbdL}esc${glyphs.kbdR} collapse`);
});

test("custom panel list moves selection without native select chrome", () => {
  const list = makePanelList(null, null, theme, { showDescription: true });
  const changes: string[] = [];
  list.on("selectionChanged", (event: any) => changes.push(event.value));
  list.options = [
    { name: "one", description: "first", value: "1" },
    { name: "two", description: "second", value: "2" },
  ];
  expect(list.selectedValue()).toBe("1");
  expect(list.moveDown()).toBe(true);
  expect(list.selectedValue()).toBe("2");
  expect(changes).toEqual(["2"]);
});

test("custom panel list keeps row metadata in a right lane", () => {
  const list = makePanelList(fakeOpentui(), null, theme, { showDescription: true, maxTextWidth: 36 });
  list.options = [
    { name: "overlay-review", rightMeta: "draft", description: "draft_overlay_review", value: "draft" },
    { name: "compact-80col", rightMeta: "failed", description: "footer clipped", value: "failed" },
  ];

  const title = list.children[0].children[0].content;
  expect(title).toContain("▍ overlay-review");
  expect(title.endsWith("draft")).toBe(true);
  expect(title.indexOf("draft")).toBeGreaterThan(title.indexOf("overlay-review") + "overlay-review".length);
  expect(list.children[1].children[0].content.endsWith("failed")).toBe(true);
});

test("custom panel list hover is distinct from keyboard selection", () => {
  const list = makePanelList(fakeOpentui(), null, theme, { showDescription: true });
  list.options = [
    { name: "one", description: "first", value: "1" },
    { name: "two", description: "second", value: "2" },
  ];
  const secondRow = list.children[1];
  secondRow.onMouseOver({ type: "over" });
  expect(list.selectedValue()).toBe("1");
  expect(list.children[1].children[0].content.startsWith(glyphs.hover)).toBe(true);
});

test("InfoPanelWidget renders structured row surfaces", () => {
  const widget = new InfoPanelWidget(null, null, theme);
  widget.update({
    eyebrow: "runtime",
    rows: [
      { label: "provider", value: "openai", detail: "configured runtime", tone: "accent" },
      { label: "model", value: "gpt-5" },
    ],
    footer: "/theme cycles semantic themes.",
  });
  expect(widget.node).toBeDefined();
});

test("ThemePanelWidget renders Paper-style preview cards", () => {
  const widget = new ThemePanelWidget(fakeOpentui(), null, theme);
  widget.update(emptyState());
  const panel = widget as any;
  const firstCard = panel.cards[0];
  const header = firstCard.children[0];
  expect(header.children[0].content).toContain("PAPER-DARK");
  expect(header.children[0].content).not.toContain(glyphs.caretStream);
  expect(header.children[1].content).toContain("default");
  expect(firstCard.children[1].children[1].content).toBe("apply the patch and rerun tests");
  expect(firstCard.children[2].children[1].content).toBe("thought for 2s");
  expect(firstCard.children[3].children[1].content).toBe(`edit Transcript.ts · +3 ${glyphs.minus}1`);
  expect(firstCard.children[4].children[0].content).toContain("⠙");
  expect(firstCard.children[4].children[1].content).toBe("shell bun test");
  expect(firstCard.children[5].content.length).toBeLessThanOrEqual(34);
  expect(firstCard.children[6].content).toContain("implement design tokens");
  expect(firstCard.marginBottom).toBe(0);
});

test("RailWidget keeps theme footer principle-facing", () => {
  const widget = new RailWidget(fakeOpentui(), null, theme);
  widget.update({
    ...emptyState(),
    ui: { ...emptyState().ui, activePanel: "theme" },
  });
  expect((widget as any).footer.content).toBe("semantic layer only · widgets unchanged");
  expect((widget as any).footer.content).not.toContain("cycle:");
  expect((widget as any).footer.content).not.toContain("high-contrast in settings");
});

test("SettingsWidget describes themes as semantic layers", () => {
  const widget = new SettingsWidget(fakeOpentui(), null, theme);
  widget.update({ ...emptyState().settings, theme: "paper-dark", diffView: "split", dirty: true });

  const themeRow = widget.node.children[1].children[0];
  const spinnerRow = widget.node.children[1].children[1];
  const reasoningRow = widget.node.children[1].children[2];
  const diffRow = widget.node.children[1].children[3];
  const mouseRow = widget.node.children[1].children[4];
  expect(themeRow.children[0].children[1].content).toBe("theme");
  expect(themeRow.children[0].children[2].content).toBe("paper-dark");
  expect(themeRow.children[1].content).toBe("  semantic layer only · widgets unchanged");
  expect(themeRow.children[1].content).not.toContain("paper-light");
  expect(themeRow.children[1].content).not.toContain("high-contrast");
  expect(spinnerRow.children[0].children[1].content).toBe("spinner");
  expect(spinnerRow.children[0].children[2].content).toBe("braille");
  expect(spinnerRow.children[1].content).toBe("  frame-based motion");
  expect(spinnerRow.children[1].content).not.toBe("  braille");
  expect(reasoningRow.children[0].children[2].content).toBe("folded");
  expect(reasoningRow.children[0].children[2].content).not.toBe("off");
  expect(reasoningRow.children[1].content).toBe("  reasoning folded");
  expect(diffRow.children[1].content).toBe("  split patch view");
  expect(mouseRow.children[1].content).toBe("  mouse and keyboard aligned");
  expect(reasoningRow.children[1].content).not.toContain("off · on");
  expect(diffRow.children[1].content).not.toContain("unified · split");
  expect(mouseRow.children[1].content).not.toContain("off · on");
});

test("UpdateWidget keeps release source URLs out of the value lane", () => {
  const widget = new UpdateWidget(fakeOpentui(), null, theme);
  widget.update({
    status: "ready",
    lastAction: "check",
    error: "",
    result: {
      current_version: "0.4.1",
      channel: "alpha",
      install_kind: "uv-tool",
      manifest_source: "https://updates.tinyagent.dev/alpha.json",
      checked_at: "2026-05-25T18:40:00Z",
      latest_version: "0.4.2",
      available: true,
      reason: "new alpha build available",
      platform: "darwin-arm64",
      active_version: "0.4.1",
      previous_version: "0.4.0",
      artifact: null,
    },
  });

  const rows = widget.node.children[1];
  const source = rows.children[3];
  const last = rows.children[4];
  expect(source.children[0].children[1].content).toBe("source");
  expect(source.children[0].children[2].content).toBe("alpha feed");
  expect(source.children[1].content).toBe("  checked release service");
  expect(source.children[0].children[1].content).not.toContain("manifest");
  expect(source.children[0].children[2].content).not.toContain("https://");
  expect(source.children[1].content).not.toContain("https://");
  expect(source.children[1].content).not.toContain("updates.tinyagent.dev");
  expect(source.children[1].content).not.toContain(".json");
  expect(last.children[0].children[1].content).toBe("last");
  expect(last.children[0].children[2].content).toBe("checked");
  expect(last.children[1].content).toBe("  2026-05-25 18:40");
  expect(widget.node.children[2].content).toBe("ready to apply · rollback available");
  expect(widget.node.children[2].content).not.toContain("/update");
});

test("RailWidget keeps headless command templates readable", () => {
  const widget = new RailWidget(fakeOpentui(), null, theme);
  widget.update({
    ...emptyState(),
    ui: { ...emptyState().ui, activePanel: "headless" },
    activeSession: {
      ...createSession("conv_headless"),
      runId: "run_overlay_refactor",
      runPath: "/Users/k/work/dev/tinyagent/.tinyagent/runs/run_overlay_refactor",
      lastSeq: 42,
      usage: { inputTokens: 14_220, outputTokens: 3_104, totalTokens: 17_324, modelCalls: 5, latencyMs: 9_220 },
      turns: [
        {
          id: "t1",
          runId: "run_overlay_refactor",
          user: "bring the panel surface in line with the Paper TUI reference",
          assistant: "",
          reasoning: [],
          tools: [],
          phase: "done",
          startedAt: "",
          completedAt: "",
        },
      ],
    },
  });

  const rows = (widget as any).headlessPanel.node.children[1];
  expect(rows.children[0].children[0].children[1].content).toBe("run");
  expect(rows.children[0].children[0].children[2].content).toBe("start task");
  expect(rows.children[0].children[1].content).toBe('  tinyagent run "<prompt>"');
  expect(rows.children[1].children[0].children[2].content).toBe("watch progress");
  expect(rows.children[1].children[1].content).toBe('  tinyagent run "<prompt>" --stream text');
  expect(rows.children[2].children[0].children[1].content).toBe("replay");
  expect(rows.children[2].children[0].children[2].content).toBe("review run");
  expect(rows.children[2].children[1].content).toBe("  tinyagent replay <run-id>");
  expect(rows.children[2].children[0].children[2].content).not.toContain("project");
  expect(rows.children[2].children[1].content).not.toContain("run_overlay_refactor");
  expect(rows.children[3].children[0].children[2].content).toBe("from step 42");
  expect(rows.children[3].children[1].content).toBe("  tinyagent fork <run-path> --at 42");
  expect(rows.children[5].children[0].children[1].content).toBe("draft skill");
  expect(rows.children[5].children[0].children[2].content).toBe("capture pattern");
  expect(rows.children[5].children[1].content).toBe("  tinyagent skills draft-from-run <run-path>");
  expect(rows.children[6].children[0].children[1].content).toBe("usage");
  expect(rows.children[6].children[0].children[2].content).toBe("17324 tok · 5 calls");
  expect(rows.children[6].children[1].content).toBe("  saved with run summary");
  expect(rows.children[7].children[0].children[1].content).toBe("bridge");
  expect(rows.children[7].children[0].children[2].content).toBe("connect clients");
  expect(rows.children[7].children[1].content).toBe("  tinyagent agent stdio --protocol tinyagent");
  expect((widget as any).headlessPanel.node.children[2].content).toBe("same trace · cli parity");
  expect(rows.children[0].children[0].children[1].content).not.toContain("json");
  expect(rows.children[6].children[0].children[1].content).not.toContain("json");
  expect(rows.children[0].children[1].content).not.toContain("--output-format");
  expect(rows.children[1].children[1].content).not.toContain("jsonl");
  expect(rows.children[1].children[1].content).not.toContain("--debug");
  expect(rows.children[6].children[1].content).not.toContain("jq");
  expect(rows.children[3].children[0].children[2].content).not.toContain("event");
  expect(rows.children[7].children[0].children[1].content).not.toContain("agent");
  expect(rows.children[7].children[0].children[2].content).not.toContain("protocol");
  expect(rows.children[5].children[0].children[2].content).not.toContain("from run");
  expect(rows.children[0].children[1].content).not.toContain("bring the panel");
  expect(rows.children[3].children[1].content).not.toContain("/Users/k/work");
});

test("RailWidget keeps ACP protocol rows terse", () => {
  const widget = new RailWidget(fakeOpentui(), null, theme);
  widget.update({
    ...emptyState(),
    ui: { ...emptyState().ui, activePanel: "acp" },
  });

  const rows = (widget as any).acpPanel.node.children[1];
  expect(rows.children[0].children[0].children[1].content).toBe("bridge");
  expect(rows.children[0].children[0].children[2].content).toBe("live session");
  expect(rows.children[0].children[1].content).toBe("  app-connected turn stream");
  expect(rows.children[1].children[0].children[2].content).toBe("app bridge");
  expect(rows.children[2].children[0].children[2].content).toBe("open session");
  expect(rows.children[2].children[1].content).toBe("  create conversation");
  expect(rows.children[3].children[0].children[2].content).toBe("stream turn");
  expect(rows.children[3].children[1].content).toBe("  send user prompt");
  expect(rows.children[4].children[0].children[2].content).toBe("stop run");
  expect(rows.children[4].children[1].content).toBe("  return control");
  expect(rows.children[5].children[0].children[2].content).toBe("resolve tool");
  expect(rows.children[5].children[1].content).toBe("  allow or deny");
  expect((widget as any).acpPanel.node.children[2].content).toBe("same trace · app parity");
  expect((widget as any).acpPanel.node.children[2].content).not.toContain("event stream");
  expect(rows.children[0].children[0].children[1].content).not.toContain("transport");
  expect(rows.children[0].children[0].children[2].content).not.toContain("json-rpc");
  expect(rows.children[0].children[1].content).not.toContain("json-rpc");
  expect(rows.children[0].children[1].content).not.toContain("stderr");
  expect(rows.children[2].children[1].content).not.toContain("session.");
  expect(rows.children[5].children[1].content).not.toContain("approval.");
});

test("RailWidget keeps model state rows terse", () => {
  const widget = new RailWidget(fakeOpentui(), null, theme);
  widget.update({
    ...emptyState(),
    provider: "openai",
    model: "gpt-5",
    approvalMode: "on-request",
    sessionMode: "normal",
    ui: { ...emptyState().ui, activePanel: "model", showReasoning: false },
  });

  const rows = (widget as any).modelPanel.node.children[1];
  expect((widget as any).modelPanel.node.children[0].content).toBe("model state");
  expect(rows.children[0].children[0].children[2].content).toBe("openai");
  expect(rows.children[0].children[1].content).toBe("  next turn");
  expect(rows.children[1].children[0].children[2].content).toBe("gpt-5");
  expect(rows.children[1].children[1].content).toBe("  generation model");
  expect(rows.children[2].children[1].content).toBe("  tool gates");
  expect(rows.children[3].children[1].content).toBe("  reasoning folded");
  expect((widget as any).modelPanel.node.children[0].content).not.toContain("runtime");
  expect(rows.children[1].children[1].content).not.toContain("selected model");
  expect(rows.children[1].children[1].content).not.toContain("active id");
  expect(rows.children[3].children[1].content).not.toContain("until requested");
});

test("renderAcpPanel uses compact state copy", () => {
  const output = renderAcpPanel();
  expect(output).toContain("bridge        live session");
  expect(output).toContain("app-connected turn stream");
  expect(output).toContain("command       app bridge");
  expect(output).toContain("tinyagent agent stdio --protocol acp");
  expect(output).toContain("start         open session");
  expect(output).toContain("create conversation");
  expect(output).toContain("prompt        stream turn");
  expect(output).toContain("send user prompt");
  expect(output).toContain("cancel        stop run");
  expect(output).toContain("approval      resolve tool");
  expect(output).toContain("allow or deny");
  expect(output).toContain("same trace · app parity");
  expect(output).not.toContain("stdio json-rpc");
  expect(output).not.toContain("stderr logs");
  expect(output).not.toContain("session.start");
  expect(output).not.toContain("session.prompt");
  expect(output).not.toContain("session.cancel");
  expect(output).not.toContain("approval.resolve");
  expect(output).not.toContain("transport     stdio json-rpc");
  expect(output).not.toContain("protocol stdout");
  expect(output).not.toContain("allocates");
  expect(output).not.toContain("diagnostics");
  expect(output).not.toContain("notifications");
});

test("renderModelLab uses compact model-state copy", () => {
  const output = renderModelLab("openai", "gpt-5");
  expect(output).toContain("model state");
  expect(output).toContain("provider      openai");
  expect(output).toContain("next turn");
  expect(output).toContain("model         gpt-5");
  expect(output).toContain("generation model");
  expect(output).not.toContain("selected model");
  expect(output).not.toContain("runtime");
  expect(output).not.toContain("active id");
  expect(output).not.toContain("active model id");
  expect(output).not.toContain("configured runtime");
});

test("ContextMenuWidget keyboard commit picks highlighted action", () => {
  const menu = new ContextMenuWidget(null, null, theme);
  let picked = "";
  menu.showAt(
    2,
    3,
    [
      { label: "Copy", value: "copy" },
      { label: "Stop", value: "stop" },
    ],
    (value) => {
      picked = value;
    },
  );
  menu.moveDown();
  expect(menu.commit()).toBe(true);
  expect(picked).toBe("stop");
});

test("CommandMapWidget exposes selectable commands", () => {
  const widget = new CommandMapWidget(fakeOpentui(), null, theme);
  widget.update("diff");
  expect(widget.selectedCommandId()).toBe("diff");
  expect((widget as any).list.children[0].children[0].content).toContain("▍ /diff");
  expect((widget as any).list.children[0].children[0].content).toContain("show git diff");
  expect(widget.moveDown()).toBe(true);
  expect(widget.selectedCommandId()).toBe("diff-stat");
});

test("CommandMapWidget keeps command rows action-only", () => {
  const widget = new CommandMapWidget(fakeOpentui(), null, theme);
  widget.update("model");

  const row = (widget as any).list.children
    .map((child: any) => child.children[0].content)
    .find((content: string) => content.includes("/model"));
  expect(row).toContain("/model");
  expect(row).toContain("show model state");
  expect(row).not.toContain("· agent");
  expect(row).not.toContain("backend");
});

test("CommandMapWidget uses the curated Paper command catalog", () => {
  const widget = new CommandMapWidget(fakeOpentui(), null, theme);
  widget.update("");

  const rows = (widget as any).list.options.map((option: any) => `${option.name} ${option.rightMeta}`).join("\n");
  expect((widget as any).list.options).toHaveLength(pickerCommands.length);
  expect((widget as any).list.children).toHaveLength(pickerCommands.length);
  expect(rows).toContain("/new");
  expect(rows).toContain("/help");
  for (const hidden of ["/always-approve", "/approve", "/deny", "/compact-mode", "/rewind", "/fork"]) {
    expect(rows).not.toContain(hidden);
  }
});

test("PickerWidget keeps slash command labels readable in the full palette", () => {
  const widget = new PickerWidget(fakeOpentui(), null, theme);
  widget.openCommandPalette(() => {});

  const picker = widget as any;
  const diffStat = picker.rows.find((row: any) => nodeText(row).includes("diff-stat"));
  expect(nodeText(diffStat)).toContain("/diff-stat");
  expect(nodeText(diffStat)).not.toContain("/diff-sta…");
  expect(picker.countText.content).toBe(`1 / ${pickerCommands.length} `);
  expect(picker.rows[0].children[0].content).toBe(`${glyphs.chevron} `);
  expect(picker.rows[0].children[0].fg).toBe(theme.accent);
  expect(diffStat.children[0].content).toBe("  ");
  expect(diffStat.children[0].fg).toBe(theme.textSubtle);
  expect(picker.rows[0].children[3].content).toContain(glyphs.enterCue);
  expect(nodeText(diffStat)).not.toContain(glyphs.enterCue);
  expect(picker.hintRow.content).toBe(`${glyphs.kbdL}↑↓${glyphs.kbdR} move   ${glyphs.kbdL}⏎${glyphs.kbdR} run   ${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(picker.hintRow.content).toContain(`${glyphs.kbdL}⏎${glyphs.kbdR} run`);
  expect(picker.hintRow.content).toContain(`${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(picker.hintRow.content).not.toContain(" · ");
  expect(picker.hintRow.content).not.toContain(`${glyphs.kbdL}esc${glyphs.kbdR} collapse`);
  expect(picker.hintRow.content).not.toContain(`${glyphs.kbdL}⏎${glyphs.kbdR} insert`);
});

test("PickerWidget mirrors the Paper slash command window", () => {
  const widget = new PickerWidget(fakeOpentui(), null, theme);
  widget.open({ trigger: "/" as const, query: "rep", start: 0, end: 4 }, candidatesForSlash("rep"), () => {});

  const picker = widget as any;
  expect(picker.titleText.content).toBe(" commands");
  expect(picker.countText.content).toBe(`5 / ${pickerCommands.length} `);
  const rows = picker.rows.map(nodeText).join("\n");
  expect(rows).toContain("/diff");
  expect(rows).toContain("/diff-stat");
  expect(rows).toContain("› /replay");
  expect(picker.rows[2].children[0].fg).toBe(theme.accent);
  expect(picker.rows[0].children[0].content).toBe("  ");
  expect(picker.rows[0].children[0].fg).toBe(theme.textSubtle);
  expect(picker.rows[2].children[3].content).toContain(glyphs.enterCue);
  expect(nodeText(picker.rows[0])).not.toContain("› /diff");
  expect(nodeText(picker.rows[1])).not.toContain("› /diff-stat");
  expect(nodeText(picker.rows[1])).not.toContain(glyphs.enterCue);
  expect(rows).toContain("/sessions");
  expect(rows).toContain("/skills");
  expect(picker.hintRow.content).toContain(`${glyphs.kbdL}⏎${glyphs.kbdR} run`);
  expect(picker.hintRow.content).toContain(`${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(picker.hintRow.content).not.toContain(`${glyphs.kbdL}esc${glyphs.kbdR} collapse`);
  expect(picker.hintRow.content).not.toContain(`${glyphs.kbdL}⏎${glyphs.kbdR} insert`);
});

test("PickerWidget keeps skill descriptions compact and un-clipped", () => {
  const widget = new PickerWidget(fakeOpentui(), null, theme);
  widget.open(
    { trigger: "$" as const, query: "", start: 0, end: 1 },
    candidatesForSkill("", [
      {
        name: "visual-check",
        path: "skills/visual-check/SKILL.md",
        description: "Capture OpenTUI scenes before calling UI work done",
      },
      {
        name: "paper-review",
        path: "skills/paper-review/SKILL.md",
        description: "Compare the terminal surface against the Paper artboard",
      },
    ]),
    () => {},
  );

  const picker = widget as any;
  expect(nodeText(picker.rows[0])).toContain("visual-check");
  expect(nodeText(picker.rows[0])).not.toContain("$visual-check");
  expect(nodeText(picker.rows[1])).toContain("paper-review");
  expect(nodeText(picker.rows[1])).not.toContain("$paper-review");
  expect(picker.rows[0].children[0].fg).toBe(theme.accent);
  expect(picker.rows[1].children[0].content).toBe("  ");
  expect(picker.rows[1].children[0].fg).toBe(theme.textSubtle);
  expect(nodeText(picker.rows[0])).toContain("capture TUI scenes");
  expect(nodeText(picker.rows[1])).toContain("compare terminal against Paper");
  expect(nodeText(picker.rows[0])).not.toContain("…");
  expect(nodeText(picker.rows[1])).not.toContain("…");
  expect(picker.hintRow.content).toBe(`${glyphs.kbdL}↑↓${glyphs.kbdR} move   ${glyphs.kbdL}⏎${glyphs.kbdR} insert   ${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(picker.hintRow.content).toContain(`${glyphs.kbdL}⏎${glyphs.kbdR} insert`);
  expect(picker.hintRow.content).toContain(`${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(picker.hintRow.content).not.toContain(" · ");
  expect(picker.hintRow.content).not.toContain(`${glyphs.kbdL}esc${glyphs.kbdR} collapse`);
  expect(picker.hintRow.content).not.toContain(`${glyphs.kbdL}⏎${glyphs.kbdR} run`);
});

test("PickerWidget mirrors the compact Paper skill window count", () => {
  const widget = new PickerWidget(fakeOpentui(), null, theme);
  widget.open(
    { trigger: "$" as const, query: "ver", start: 0, end: 4 },
    candidatesForSkill("ver", [
      { name: "verify", path: "skills/verify/SKILL.md", description: "run app, observe" },
      { name: "review", path: "skills/review/SKILL.md", description: "review the diff" },
      { name: "loop", path: "skills/loop/SKILL.md", description: "run on interval" },
      { name: "visual-check", path: "skills/visual-check/SKILL.md", description: "capture snapshots" },
      { name: "paper-review", path: "skills/paper-review/SKILL.md", description: "compare against Paper" },
      { name: "fix-ci", path: "skills/fix-ci/SKILL.md", description: "debug checks" },
      { name: "ship", path: "skills/ship/SKILL.md", description: "prepare a PR" },
      { name: "smoke", path: "skills/smoke/SKILL.md", description: "quickly verify" },
      { name: "docs", path: "skills/docs/SKILL.md", description: "write docs" },
      { name: "perf", path: "skills/perf/SKILL.md", description: "profile latency" },
      { name: "release", path: "skills/release/SKILL.md", description: "release notes" },
    ]),
    () => {},
  );

  const picker = widget as any;
  expect(picker.countText.content).toBe("3 / 11 ");
  expect(picker.rows).toHaveLength(3);
  expect(nodeText(picker.rows[0])).toContain("verify");
  expect(nodeText(picker.rows[1])).toContain("review");
  expect(nodeText(picker.rows[2])).toContain("loop");
  expect(nodeText(picker.rows[0])).not.toContain("$verify");
  expect(nodeText(picker.rows[0])).toContain("run app, observe");
  expect(nodeText(picker.rows[2])).toContain("run on interval");
});

test("PickerWidget mirrors the Paper filtered-file header", () => {
  const widget = new PickerWidget(fakeOpentui(), null, theme);
  widget.open(
    { trigger: "@" as const, query: "tra", start: 10, end: 14 },
    candidatesForFile("tra", ["src/ui/widgets/Transcript.ts", "tests/ui/transcript.test.ts", "docs/TRANSCRIPT.md", "README.md"], {
      "src/ui/widgets/Transcript.ts": { bytes: 12 * 1024, mtimeMs: 30 },
      "tests/ui/transcript.test.ts": { bytes: 4 * 1024, mtimeMs: 20 },
      "docs/TRANSCRIPT.md": { bytes: 2 * 1024, mtimeMs: 10 },
      "README.md": { bytes: 3 * 1024, mtimeMs: 100 },
    }),
    () => {},
  );

  const picker = widget as any;
  expect(picker.titleText.content).toBe(" files matching tra");
  expect(picker.countText.content).toBe("4 ");
  expect(nodeText(picker.rows[0])).toContain("src/ui/widgets/Transcript.ts");
  expect(nodeText(picker.rows[0])).toContain("12kb");
  expect(picker.rows[0].children[0].fg).toBe(theme.accent);
  expect(nodeText(picker.rows[3])).toContain("— recent —");
  expect(picker.rows[3].border).toEqual(["top"]);
  expect(nodeText(picker.rows[4])).toContain("README.md");
  expect(nodeText(picker.rows[4])).toContain("3kb");
  expect(picker.rows[4].children[0].content).toBe("  ");
  expect(picker.rows[4].children[0].fg).toBe(theme.textSubtle);
  picker.moveDown();
  picker.moveDown();
  picker.moveDown();
  expect((widget as any).selectedIndex).toBe(4);
});

test("HistorySearchWidget cycles matches and commits", () => {
  const widget = new HistorySearchWidget(null, null, theme);
  let picked: string | null = null;
  widget.open(["fix bug", "add feature", "fix typo"], (value) => {
    picked = value;
  });
  widget.appendChar("f");
  widget.appendChar("i");
  widget.appendChar("x");
  widget.cycle();
  widget.commit();
  expect(picked === "fix bug" || picked === "fix typo").toBe(true);
});

test("HistorySearchWidget uses picker header state instead of a query row", () => {
  const widget = new HistorySearchWidget(fakeOpentui(), null, theme);
  widget.open(["apply theme tokens", "review the overlay state"], () => {});
  for (const ch of "over") widget.appendChar(ch);

  const history = widget as any;
  expect(history.title.content).toBe(" history · over");
  expect(history.result.content).toContain(`${glyphs.chevron} review the overlay state`);
  expect(history.hint.content).toContain("type to filter");
  expect(history.hint.content).toBe(`type to filter   ${glyphs.kbdL}^R${glyphs.kbdR} next   ${glyphs.kbdL}⏎${glyphs.kbdR} use   ${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(history.hint.content).not.toContain(`${glyphs.kbdL}type${glyphs.kbdR}`);
  expect(history.hint.content).toContain(`${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(history.hint.content).not.toContain(" · ");
  expect(history.hint.content).not.toContain(`${glyphs.kbdL}esc${glyphs.kbdR} collapse`);
  expect(history.hint.content).not.toContain(`${glyphs.kbdL}esc${glyphs.kbdR} close`);
  expect(history.resultRow.backgroundColor).toBe(theme.selectionBg);
  expect(history.node.children.some((child: any) => String(child.content ?? "").startsWith("query"))).toBe(false);
});

test("PickerWidget collapses zero-result states to a non-selectable label", () => {
  const widget = new PickerWidget(fakeOpentui(), null, theme);
  const detection = { trigger: "/" as const, query: "zzzz", start: 0, end: 5 };
  widget.open(detection, [], () => {});

  const picker = widget as any;
  expect(picker.header.visible).toBe(false);
  expect(picker.optionsBox.visible).toBe(false);
  expect(picker.hintWrap.visible).toBe(false);
  expect(picker.emptyRow.visible).toBe(true);
  expect(picker.rows).toHaveLength(0);
  expect(picker.emptyRow.content).toBe(`no matches · ${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(picker.emptyRow.content).not.toContain(`${glyphs.kbdL}esc${glyphs.kbdR} collapse`);
  expect(widget.commit()).toBe(false);

  widget.open(
    { trigger: "@" as const, query: "com", start: 0, end: 4 },
    [{ label: "src/ui/widgets/Composer.ts", insert: "@src/ui/widgets/Composer.ts " }],
    () => {},
  );
  expect(picker.header.visible).toBe(true);
  expect(picker.optionsBox.visible).toBe(true);
  expect(picker.hintWrap.visible).toBe(true);
  expect(picker.emptyRow.visible).toBe(false);
  expect(picker.rows.length).toBeGreaterThan(0);
  expect(picker.hintRow.content).toContain("move");
  expect(picker.hintRow.content).toContain(`${glyphs.kbdL}⏎${glyphs.kbdR} insert`);
  expect(picker.hintRow.content).toContain(`${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(picker.hintRow.content).not.toContain(`${glyphs.kbdL}esc${glyphs.kbdR} collapse`);
});

test("PickerWidget keeps a ranked context window around the best mention match", () => {
  const widget = new PickerWidget(fakeOpentui(), null, theme);
  widget.open(
    { trigger: "/" as const, query: "rep", start: 0, end: 4 },
    [
      { label: "/diff", description: "show git diff", insert: "/diff " },
      { label: "/diff-stat", description: "show diff summary", insert: "/diff-stat " },
      { label: "/replay", description: "replay current run", insert: "/replay " },
      { label: "/sessions", description: "list sessions", insert: "/sessions " },
      { label: "/skills", description: "open skill forge", insert: "/skills " },
    ],
    () => {},
  );

  const picker = widget as any;
  expect(picker.countText.content).toBe("3 / 5 ");
  expect(picker.rows).toHaveLength(5);
  expect(nodeText(picker.rows[2])).toContain("› /replay");
  expect(picker.rows[2].children[0].fg).toBe(theme.accent);
  expect(picker.rows[2].children[3].content).toContain(glyphs.enterCue);
  expect(picker.rows[0].children[0].content).toBe("  ");
  expect(nodeText(picker.rows[0])).not.toContain("› /diff");
  expect(picker.hintRow.content).toContain(`${glyphs.kbdL}⏎${glyphs.kbdR} run`);
  expect(picker.hintRow.content).toContain(`${glyphs.kbdL}esc${glyphs.kbdR} cancel`);
  expect(picker.hintRow.content).not.toContain(`${glyphs.kbdL}esc${glyphs.kbdR} collapse`);
  expect(picker.hintRow.content).not.toContain(`${glyphs.kbdL}⏎${glyphs.kbdR} insert`);
});

test("TranscriptWidget toggles reasoning and tool output from clickable rows", () => {
  const widget = new TranscriptWidget(fakeOpentui(), null, theme);
  widget.setTurns([
    {
      id: "turn1",
      runId: "run1",
      user: "inspect transcript interactivity",
      assistant: "Done.",
      reasoning: [
        {
          id: "reason1",
          text: "Need a clickable reasoning header.",
          completed: true,
          startedAt: "2026-05-25T20:48:00.000Z",
          completedAt: "2026-05-25T20:48:04.000Z",
        },
      ],
      tools: [
        {
          id: "tool1",
          tool: "search",
          label: "search",
          argsSummary: '"reasoning" in tui/src',
          status: "done",
          output: "Transcript.ts:160\nmount.ts:228\nvisual-check.ts:166",
          startedAt: "2026-05-25T20:48:00.000Z",
          completedAt: "2026-05-25T20:48:00.500Z",
        },
      ],
      phase: "done",
      startedAt: "20:48",
      completedAt: "",
    },
  ]);

  const card = (widget as any).cards.get("turn1");
  expect(card.user.content).toContain("20:48");
  expect(card.reasoning.content).toContain("thought for 4s");
  expect(card.reasoningBox.visible).toBe(true);
  expect(card.reasoningBody.visible).toBe(false);
  card.reasoning.onMouseDown({ type: "down", button: 0 });
  expect(card.reasoningBody.visible).toBe(true);

  const toolRow = card.tools.children[0];
  expect(toolRow.content).toContain("3 lines");
  expect(toolRow.content).toContain("0.5s");
  expect(toolRow.content).not.toContain(glyphs.treeBranch);
  toolRow.onMouseDown({ type: "down", button: 0 });
  expect(toolRow.content).toContain(glyphs.treeBranch);
});

test("TranscriptWidget shows running tools in the right meta lane", () => {
  const widget = new TranscriptWidget(fakeOpentui(), null, theme);
  widget.setTurns([
    {
      id: "turn1",
      runId: "run1",
      user: "edit a file",
      assistant: "",
      reasoning: [],
      tools: [
        {
          id: "tool1",
          tool: "edit",
          label: "edit",
          argsSummary: "src/ui/widgets/Transcript.ts",
          status: "running",
          output: "",
          startedAt: "2026-05-25T20:48:00.000Z",
        },
      ],
      phase: "streaming",
      startedAt: "20:48",
      completedAt: "",
    },
  ]);

  const card = (widget as any).cards.get("turn1");
  expect(card.user.content).toContain("20:48 · just now");
  expect(card.tools.children[0].content).toContain("running…");
});

test("TranscriptWidget keeps dotted tool ids out of the visible lane", () => {
  const widget = new TranscriptWidget(fakeOpentui(), null, theme);
  widget.setTurns([
    {
      id: "turn1",
      runId: "run1",
      user: "review activity overlay",
      assistant: "",
      reasoning: [],
      tools: [
        {
          id: "tool1",
          tool: "plan.step",
          label: "patch activity panel",
          argsSummary: "PlanBoardWidget copy",
          status: "running",
          output: "",
          startedAt: "2026-05-25T20:48:00.000Z",
        },
      ],
      phase: "streaming",
      startedAt: "20:48",
      completedAt: "",
    },
  ]);

  const card = (widget as any).cards.get("turn1");
  expect(card.tools.children[0].content).toContain("patch    PlanBoardWidget copy");
  expect(card.tools.children[0].content).not.toContain("plan.ste");
  expect(card.tools.children[0].content).not.toContain("plan.step");
});

test("renderTranscript keeps dotted tool ids out of the visible lane", () => {
  const output = renderTranscript([
    {
      id: "turn1",
      runId: "run1",
      user: "review activity overlay",
      assistant: "",
      reasoning: [],
      tools: [
        {
          id: "tool1",
          tool: "plan.step",
          label: "patch activity panel",
          argsSummary: "PlanBoardWidget copy",
          status: "running",
          output: "",
        },
      ],
      phase: "streaming",
      startedAt: "20:48",
      completedAt: "",
    },
  ]);

  expect(output).toContain("⠋ patch   patch activity panel");
  expect(output).not.toContain("plan.ste");
  expect(output).not.toContain("plan.step");
});

test("TranscriptWidget opens active reasoning while a turn is streaming", () => {
  const widget = new TranscriptWidget(fakeOpentui(), null, theme);
  widget.setTurns([
    {
      id: "turn1",
      runId: "run1",
      user: "stream the current turn",
      assistant: "",
      reasoning: [
        {
          id: "reason1",
          text: "Active reasoning should be visible while the run is moving.",
          completed: true,
          startedAt: "2026-05-25T20:48:00.000Z",
          completedAt: "2026-05-25T20:48:04.000Z",
        },
      ],
      tools: [],
      phase: "streaming",
      startedAt: "",
      completedAt: "",
    },
  ]);

  const card = (widget as any).cards.get("turn1");
  expect(card.reasoningBody.visible).toBe(true);
  expect(card.reasoning.content).toContain("thought for 4s");
  expect(card.reasoning.content).toContain("⌜r⌟ collapse");
});

test("TranscriptWidget hides reasoning implementation block counts", () => {
  const widget = new TranscriptWidget(fakeOpentui(), null, theme);
  widget.setTurns([
    {
      id: "turn1",
      runId: "run1",
      user: "summarize the panel",
      assistant: "Done.",
      reasoning: [
        {
          id: "reason1",
          text: "No timing metadata should still keep the header product-facing.",
          completed: true,
        },
      ],
      tools: [],
      phase: "done",
      startedAt: "",
      completedAt: "",
    },
  ]);

  const card = (widget as any).cards.get("turn1");
  expect(card.reasoning.content).toContain("thought");
  expect(card.reasoning.content).not.toContain("block");
});

test("TranscriptWidget renders a bounded inline patch preview from DiffState", () => {
  const widget = new TranscriptWidget(fakeOpentui(), null, theme);
  widget.setViewportWidth(160);
  widget.setTurns([
    {
      id: "turn1",
      runId: "run1",
      user: "apply the patch",
      assistant: "Here is the patch.\n\nOnce that lands the transcript can keep moving.",
      reasoning: [],
      tools: [],
      phase: "done",
      startedAt: "",
      completedAt: "",
    },
  ]);
  widget.setDiff({
    paths: ["src/ui/widgets/Transcript.ts"],
    truncated: false,
    text: [
      "diff --git a/src/ui/widgets/Transcript.ts b/src/ui/widgets/Transcript.ts",
      "@@ -158,6 +158,8 @@ function applyChunk(card, next) {",
      "   if (next !== card.lastAssistant) {",
      "+    card.assistant.content = next;",
      "+    card.lastAssistant = next;",
      "-    card.assistant = rebuild(next);",
      "   }",
    ].join("\n"),
  });

  const preview = (widget as any).patchPreview;
  const card = (widget as any).cards.get("turn1");
  expect(preview.visible).toBe(true);
  expect(card.assistant.content).toContain("Here is the patch.");
  expect(card.assistantTail.content).toContain("Once that lands");
  expect(card.assistantTail.visible).toBe(true);
  expect(card.inner.children.indexOf(preview)).toBeLessThan(card.inner.children.indexOf(card.assistantTail));
  const patchHeader = (widget as any).patchHeader.content;
  expect(patchHeader).toContain("PATCH  src/ui/widgets/Transcript.ts");
  expect(patchHeader).toContain(`+2  ${glyphs.minus}1`);
  expect(patchHeader.indexOf(`+2  ${glyphs.minus}1`)).toBeGreaterThan(patchHeader.indexOf("PATCH") + 70);
  expect(patchHeader).toContain("⌜⏎⌟ apply");
  expect(patchHeader).toContain("⌜d⌟ diff");
  expect((widget as any).patchBody.content).toContain("159 +");
  expect((widget as any).patchBody.content).toContain("159 -");

  widget.setDiff(null);
  expect(preview.visible).toBe(false);
  expect(card.assistant.content).toContain("Once that lands");
  expect(card.assistantTail.visible).toBe(false);
  expect(card.inner.children).not.toContain(preview);
});

function fakeOpentui(): any {
  class Node {
    children: any[] = [];
    visible = true;
    enableLayout = true;
    constructor(_ctx: any, options: any) {
      Object.assign(this, options);
    }
    add(child: any) {
      this.children.push(child);
    }
    remove(childOrId: any) {
      this.children = this.children.filter((child) => child !== childOrId && child.id !== childOrId);
    }
    focus() {}
    blur() {}
    on() {}
    off() {}
  }
  return { BoxRenderable: Node, ScrollBoxRenderable: Node, TextRenderable: Node };
}
