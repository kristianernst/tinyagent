// Smoke tests for widget classes. Without a TTY/opentui we exercise the
// headless code paths and assert the widgets construct, update, and never
// throw on empty/partial state.

import { expect, test } from "bun:test";
import { ContextWidget } from "../src/ui/widgets/ContextWidget";
import { DebugWidget } from "../src/ui/widgets/DebugWidget";
import { EvalLabWidget } from "../src/ui/widgets/EvalLabWidget";
import { FailureWidget } from "../src/ui/widgets/FailureWidget";
import { PlanBoardWidget } from "../src/ui/widgets/PlanBoardWidget";
import { ReplayWidget } from "../src/ui/widgets/ReplayWidget";
import { SessionsWidget } from "../src/ui/widgets/SessionsWidget";
import { SkillForgeWidget } from "../src/ui/widgets/SkillForgeWidget";
import { ToolTimelineWidget } from "../src/ui/widgets/ToolTimelineWidget";
import { UpdateWidget } from "../src/ui/widgets/UpdateWidget";
import { UsageWidget } from "../src/ui/widgets/UsageWidget";
import { DividerWidget } from "../src/ui/widgets/Divider";
import { ContextMenuWidget } from "../src/ui/widgets/ContextMenu";
import { HistorySearchWidget } from "../src/ui/widgets/HistorySearch";
import { resolveTheme } from "../src/ui/theme";
import { emptyState, createSession } from "../src/state/reducer";

const theme = resolveTheme("tiny-dark");

test("ToolTimelineWidget handles empty + populated state without throwing", () => {
  const widget = new ToolTimelineWidget(null, null, theme);
  widget.update([]);
  widget.update([
    { id: "1", tool: "shell", label: "shell ls", argsSummary: "ls", status: "done", output: "ok" },
  ]);
  expect(widget.node).toBeDefined();
});

test("PlanBoardWidget reflects sessionMode", () => {
  const widget = new PlanBoardWidget(null, null, theme);
  widget.update(emptyState());
  widget.update({ ...emptyState(), sessionMode: "plan" });
  expect(widget.node).toBeDefined();
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

test("ReplayWidget tolerates null replay", () => {
  const widget = new ReplayWidget(null, null, theme);
  widget.update(null);
  widget.update({
    runId: "run_x",
    events: [],
    cursorSeq: 0,
    rawEvent: null,
    projected: null,
    forkDir: "",
    replayMs: 0,
  });
  expect(widget.node).toBeDefined();
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
