import { expect, test } from "bun:test";
import { mountApp } from "../src/ui/mount";
import { createRendererHost } from "../src/ui/renderer";
import { Store } from "../src/state/store";
import { createSession, emptyState } from "../src/state/reducer";
import { resolveTheme } from "../src/ui/theme";

// Smoke test for the rebuilt shell. Confirms the new mount wiring constructs
// without throwing — every widget (chrome bar, transcript, composer, picker,
// approval, history search, context menu) instantiates against the headless
// renderer host, the palette shim resolves, and refresh() doesn't blow up on
// the default state.

test("mountApp wires the Paper shell with chrome bar, picker, and right-side panel overlay", async () => {
  const host = await createRendererHost();
  expect(host.kind).toBe("headless");
  const store = new Store(emptyState());
  const mount = mountApp(host, store);

  // New surface present.
  expect(mount.chromeBar).toBeDefined();
  expect(mount.picker).toBeDefined();

  // Back-compat shim is wired with the right methods app.tsx still calls.
  expect(mount.palette).toBeDefined();
  expect(typeof mount.palette.setOnSelect).toBe("function");
  expect(typeof mount.palette.show).toBe("function");
  expect(typeof mount.palette.hide).toBe("function");
  expect(typeof mount.palette.commit).toBe("function");

  // mentionMenu and picker are the same widget so the visibility check in
  // app.tsx ("an overlay is consuming Enter") still works regardless of mode.
  expect(mount.mentionMenu).toBe(mount.picker);

  // Composer and approval are present.
  expect(mount.composer).toBeDefined();
  expect(mount.approval).toBeDefined();
  expect(mount.transcript).toBeDefined();
  expect(mount.rail.isVisible()).toBe(false);

  // Refresh does not throw against an empty store. This exercises every
  // widget's `update(state)` path, including the new chrome bar.
  mount.refresh();
  const chrome = mount.chromeBar as any;
  const theme = resolveTheme("paper-dark");
  expect(chrome.ctxText.content).toBe("  0%");
  expect(chrome.phasePill.fg).toBe(theme.textMuted);
  expect(chrome.phasePill.bg).toBe(theme.surfaceMuted);

  const state = emptyState();
  state.ui.activePanel = "sessions";
  state.sessions = [
    {
      conversation_id: "conv_a",
      title: "alpha",
      status: "done",
      active_turn_id: null,
      created_at: "",
      updated_at: "now",
      workspace: "tinyagent",
      turn_count: 1,
    },
    {
      conversation_id: "conv_b",
      title: "beta",
      status: "done",
      active_turn_id: null,
      created_at: "",
      updated_at: "now",
      workspace: "tinyagent",
      turn_count: 2,
    },
  ];
  store.set(state);
  mount.refresh();
  expect(mount.rail.isVisible()).toBe(true);
  expect(mount.composer.node.visible).toBe(false);
  expect(mount.rail.selectedValue()).toBe("conv_a");
  expect(mount.rail.moveSelection(1)).toBe(true);
  expect(mount.rail.selectedValue()).toBe("conv_b");
  store.set({ ...store.get(), ui: { ...store.get().ui, activePanel: "help" } });
  mount.refresh();
  expect(mount.rail.selectedCommandId()).toBe("new");
  mount.closePanelOverlay();
  expect(store.get().ui.activePanel).toBe("transcript");
  expect(store.get().ui.rightRail).toBe(false);
  mount.refresh();
  expect(mount.composer.node.visible).toBe(true);

  store.set({ ...store.get(), ui: { ...store.get().ui, activePanel: "debug", paletteOpen: true } });
  mount.refresh();
  expect(mount.rail.isVisible()).toBe(true);
  expect(mount.picker.isVisible()).toBe(false);
  expect(store.get().ui.paletteOpen).toBe(false);

  mount.composer.activateHint("history");
  expect(mount.historySearch.isOpen()).toBe(true);
  mount.contextMenu.showAt(2, 2, [{ label: "Copy last reply", description: "Copy assistant text", value: "copy-last" }], () => {});
  expect(mount.contextMenu.isVisible()).toBe(true);
  store.set({ ...store.get(), ui: { ...store.get().ui, activePanel: "sessions" } });
  mount.refresh();
  expect(mount.historySearch.isOpen()).toBe(false);
  expect(mount.contextMenu.isVisible()).toBe(false);

  const diffState = emptyState();
  diffState.activeSession = {
    ...createSession("conv_diff"),
    diff: {
      paths: ["README.md"],
      truncated: false,
      text: ["diff --git a/README.md b/README.md", "@@ -1 +1 @@", "-old", "+new"].join("\n"),
    },
  };
  store.set(diffState);
  mount.refresh();
  expect((mount.transcript as any).patchPreview.visible).toBe(true);
  store.set({ ...store.get(), ui: { ...store.get().ui, activePanel: "diff" } });
  mount.refresh();
  expect((mount.transcript as any).patchPreview.visible).toBe(false);
  expect(mount.rail.isVisible()).toBe(true);

  // Chrome bar mouse targets open the same overlay surfaces as slash commands.
  mount.chromeBar.activate("sessions");
  expect(store.get().ui.activePanel).toBe("sessions");
  mount.chromeBar.activate("model");
  expect(store.get().ui.activePanel).toBe("model");
  mount.chromeBar.activate("diff");
  expect(store.get().ui.activePanel).toBe("diff");
  mount.chromeBar.activate("usage");
  expect(store.get().ui.activePanel).toBe("usage");

  const wideHost = { ...host, width: 120 };
  const wideStore = new Store(emptyState());
  const wideMount = mountApp(wideHost, wideStore);
  const wideChrome = wideMount.chromeBar as any;
  const branchState = {
    ...emptyState(),
    phase: "streaming" as const,
    model: "gpt-5",
    workspaces: [{ workspace_id: "ws1", root: "", name: "tinyagent" }],
    activeWorkspaceId: "ws1",
    activeSession: {
      ...createSession("conv_wide"),
      git: { branch: "ta-review-gated-learning" } as any,
      usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, modelCalls: 0, latencyMs: 0 },
    },
  };
  wideChrome.update(branchState, 120);
  expect(wideChrome.leftText.content).toContain("◆ tinyagent");
  expect(wideChrome.leftText.content).not.toContain("●");
  expect(wideChrome.leftText.content).toContain("⎇ ta-");
  expect(wideChrome.leftText.content).not.toContain("ta-review-gated-learning");
  wideChrome.update(branchState, 99);
  expect(wideChrome.ctxText.content).toBe("  0%");
  expect(wideChrome.ctxText.content).not.toContain("ctx");
  wideChrome.update(branchState, 100);
  expect(wideChrome.ctxText.content).toContain("ctx");
  wideChrome.update(
    {
      ...branchState,
      activeSession: {
        ...branchState.activeSession,
        pendingApproval: {
          approval_id: "approval_queued",
          tool_name: "shell",
          action_kind: "run-command",
          risk: "high",
          command: "npm test -- --watch",
          args_preview: "npm test -- --watch",
        },
        usage: { inputTokens: 0, outputTokens: 0, totalTokens: 30_720, modelCalls: 0, latencyMs: 0 },
      },
    },
    110,
  );
  expect(wideChrome.leftText.content).toContain("ws : tinyagent");
  expect(wideChrome.leftText.content).toContain("model : gpt-5");
  expect(wideChrome.leftText.content).not.toContain("ta-r");
  expect(wideChrome.leftText.content).not.toContain("●");
  expect(wideChrome.transientText.content).toContain("approve queued");
  expect(wideChrome.ctxText.content).toContain("ctx");
  wideChrome.update({ ...branchState, phase: "idle" as const }, 120);
  expect(wideChrome.leftText.content).toContain("⎇ ta-");
  expect(wideChrome.leftText.content).not.toContain("ta-review-gated-learning");
  wideChrome.update(
    {
      ...branchState,
      phase: "idle" as const,
      updatePanel: {
        status: "ready" as const,
        lastAction: "auto-check",
        error: "",
        result: {
          current_version: "0.4.1",
          latest_version: "0.4.2",
          channel: "alpha",
          install_kind: "standalone",
          manifest_source: "test",
          checked_at: "",
          available: true,
          reason: "newer version",
          platform: "darwin-arm64",
          active_version: "0.4.1",
          previous_version: "",
        },
      },
    },
    120,
  );
  expect(wideChrome.leftText.content).toContain("ws : tinyagent");
  expect(wideChrome.leftText.content).toContain("model : gpt-5");
  expect(wideChrome.leftText.content).toContain("⎇ …");
  expect(wideChrome.leftText.content).not.toContain("●");
  wideChrome.update(branchState, 160);
  expect(wideChrome.leftText.content).toContain("ws : tinyagent");
  expect(wideChrome.leftText.content).toContain("model : gpt-5");
  expect(wideChrome.leftText.content).toContain("⎇ ta-review-gated-learning");
  expect(wideChrome.spinnerText.content).toHaveLength(3);
  expect(wideChrome.spinnerText.content.startsWith(" ")).toBe(true);
  expect(wideChrome.spinnerText.content.endsWith(" ")).toBe(true);
  expect(wideChrome.ctxText.content).toContain("0%");
  expect(wideChrome.ctxText.content).not.toContain("brand");
  wideChrome.update(
    {
      ...branchState,
      activeSession: {
        ...branchState.activeSession,
        usage: { inputTokens: 0, outputTokens: 0, totalTokens: Math.round(128_000 * 0.82), modelCalls: 0, latencyMs: 0 },
      },
    },
    160,
  );
  expect(wideChrome.ctxText.content).toContain("82% — warning");
  expect(wideChrome.ctxText.fg).toBe(theme.warning);
  wideChrome.update(
    {
      ...branchState,
      activeSession: {
        ...branchState.activeSession,
        usage: { inputTokens: 0, outputTokens: 0, totalTokens: Math.round(128_000 * 0.96), modelCalls: 0, latencyMs: 0 },
      },
    },
    160,
  );
  expect(wideChrome.ctxText.content).toContain("96% — danger");
  expect(wideChrome.ctxText.fg).toBe(theme.danger);
  wideChrome.update(
    {
      ...emptyState(),
      workspaces: [{ workspace_id: "ws1", root: "", name: "tinyagent" }],
      activeWorkspaceId: "ws1",
      activeSession: {
        ...createSession("conv_tight"),
        git: { branch: "ta-review-gated-learning" } as any,
        usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, modelCalls: 0, latencyMs: 0 },
      },
    },
    80,
  );
  expect(wideChrome.leftText.content).toContain("⎇");
  const tightBranchSegment = wideChrome.leftSegments.find((segment: any) => segment.action === "diff");
  expect(tightBranchSegment).toBeDefined();
  wideChrome.leftText.onMouseMove({ type: "move", x: tightBranchSegment.start });
  expect(wideChrome.leftText.content).toContain("ta-r");
  expect(wideChrome.leftText.content).not.toContain(`${"⎇"} …`);
  wideChrome.leftText.onMouseOut();
  expect(wideChrome.leftText.content).toContain("⎇");
  wideMount.destroy();

  // The rendered identity hit map also routes real mouse events, not only the
  // direct test helper.
  const sessionsSegment = chrome.leftSegments.find((segment: any) => segment.action === "sessions");
  expect(sessionsSegment).toBeDefined();
  chrome.leftText.onMouseDown({ type: "down", button: 0, x: sessionsSegment.start });
  expect(store.get().ui.activePanel).toBe("sessions");

  const withUpdate = {
    ...store.get(),
    updatePanel: {
      status: "ready" as const,
      lastAction: "auto-check",
      error: "",
      result: {
        current_version: "0.4.1",
        latest_version: "0.4.2",
        channel: "alpha",
        install_kind: "standalone",
        manifest_source: "test",
        checked_at: "",
        available: true,
        reason: "newer version",
        platform: "darwin-arm64",
        active_version: "0.4.1",
        previous_version: "",
      },
    },
  };
  store.set(withUpdate);
  mount.refresh();
  const updateSegment = chrome.transientSegments.find((segment: any) => segment.action === "update");
  expect(updateSegment).toBeDefined();
  expect(chrome.transientText.fg).toBe(theme.accent);
  expect(chrome.transientText.bg).toBe(theme.accentSoft);
  chrome.transientText.onMouseDown({ type: "down", button: 0, x: updateSegment.start });
  expect(store.get().ui.activePanel).toBe("update");

  // A queued approval during streaming stays in the chrome and keeps the root
  // surface usable. The blocking modal appears only once the app enters the
  // approval phase.
  store.set({
    ...emptyState(),
    phase: "streaming",
    workspaces: [{ workspace_id: "ws1", root: "", name: "tinyagent" }],
    activeWorkspaceId: "ws1",
    activeSession: {
      ...createSession("conv_queued_approval"),
      pendingApproval: {
        approval_id: "approval_queued",
        tool_name: "shell",
        action_kind: "run-command",
        risk: "high",
        command: "npm test -- --watch",
        args_preview: "npm test -- --watch",
      },
      usage: { inputTokens: 0, outputTokens: 0, totalTokens: 30_720, modelCalls: 0, latencyMs: 0 },
    },
  });
  mount.refresh();
  expect(chrome.phasePill.content).toContain("streaming");
  expect(chrome.transientText.content).toContain("approve queued");
  expect(chrome.ctxText.content).toContain("24%");
  expect(mount.approval.current()).toBeNull();
  expect(mount.approval.node.visible).toBe(false);
  expect(mount.composer.node.visible).toBe(true);

  // When the app itself is in approval phase, the phase pill is the approval
  // affordance; don't duplicate that state with an extra queued transient.
  store.set({
    ...emptyState(),
    phase: "approval",
    workspaces: [{ workspace_id: "ws1", root: "", name: "tinyagent" }],
    activeWorkspaceId: "ws1",
    activeSession: {
      ...createSession("conv_approval"),
      pendingApproval: {
        approval_id: "approval_phase",
        tool_name: "shell",
        action_kind: "run-command",
        risk: "high",
        command: "rm -rf node_modules",
        args_preview: "rm -rf node_modules",
      },
      usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, modelCalls: 0, latencyMs: 0 },
    },
  });
  mount.refresh();
  expect(chrome.phasePill.content).toContain("approve");
  expect(chrome.transientText.content).not.toContain("approve queued");
  expect(mount.composer.node.visible).toBe(false);

  // Idle plan mode is already represented by the phase pill, so it should not
  // duplicate itself in the transient stack.
  store.set({
    ...emptyState(),
    sessionMode: "plan",
    workspaces: [{ workspace_id: "ws1", root: "", name: "tinyagent" }],
    activeWorkspaceId: "ws1",
    activeSession: createSession("conv_plan"),
  });
  mount.refresh();
  expect(chrome.phasePill.content).toContain("plan");
  expect(chrome.transientText.content).not.toContain("plan");

  // Transient chrome stays restrained: at most two concrete pills are shown,
  // and the rest collapse into a clickable overflow pill.
  const overflowState = {
    ...withUpdate,
    phase: "failed" as const,
    sessionMode: "plan" as const,
    activeSession: {
      ...withUpdate.activeSession!,
      pendingApproval: {
        approval_id: "approval_overflow",
        tool_name: "shell",
        action_kind: "run-command",
        risk: "high",
        command: "rm -rf node_modules",
        args_preview: "rm -rf node_modules",
      },
      usage: {
        ...(store.get().activeSession?.usage ?? { inputTokens: 0, outputTokens: 0, totalTokens: 0, modelCalls: 0, latencyMs: 0 }),
        totalTokens: 128_000,
      },
    },
  };
  store.set(overflowState);
  mount.refresh();
  expect(chrome.phasePill.content).toContain("failed");
  expect(chrome.leftText.content).toContain("default");
  expect(chrome.leftText.content).not.toContain("ws : tinyagent");
  expect(chrome.phasePill.fg).toBe(theme.danger);
  expect(chrome.phasePill.bg).toBe(theme.dangerSoft);
  expect(chrome.transientText.content).toContain("compact");
  expect(chrome.transientText.content).toContain("approve queued");
  expect(chrome.transientText.content).toContain("+2");
  expect(chrome.transientText.content).not.toContain("failed");
  expect(chrome.transientText.content).not.toContain("update 0.4.2");
  expect(chrome.transientText.content).not.toContain("plan");
  expect(chrome.transientText.fg).toBe(theme.danger);
  expect(chrome.transientText.bg).toBe(theme.dangerSoft);
  const overflowSegment = chrome.transientSegments.find((segment: any) => chrome.transientText.content.slice(segment.start, segment.end).includes("+2"));
  expect(overflowSegment?.action).toBe("usage");
  chrome.transientText.onMouseDown({ type: "down", button: 0, x: overflowSegment.start });
  expect(store.get().ui.activePanel).toBe("usage");
  mount.closePanelOverlay();
  mount.refresh();
  expect(store.get().ui.activePanel).toBe("transcript");

  // Composer hint chips are active surfaces, not decorative labels. Clicking
  // the slash hint uses the same mention picker path as typing `/`; clicking
  // history opens the same overlay as Ctrl+R.
  mount.composer.activateHint("/");
  expect(mount.composer.value()).toBe("/");
  expect(store.get().mention.trigger).toBe("/");
  expect(mount.picker.isVisible()).toBe(true);
  const slashRuns: string[] = [];
  mount.setOnSlashCommand((id) => slashRuns.push(id));
  mount.composer.setValue("/rep");
  expect(mount.picker.commit()).toBe(true);
  expect(slashRuns).toEqual(["replay"]);
  expect(mount.composer.value()).toBe("");
  expect(store.get().mention.trigger).toBeNull();
  mount.composer.activateHint("history");
  expect(mount.picker.isVisible()).toBe(false);
  expect(mount.historySearch.isOpen()).toBe(true);
  mount.composer.activateHint("@");
  expect(mount.historySearch.isOpen()).toBe(false);
  expect(store.get().mention.trigger).toBe("@");
  expect(mount.picker.isVisible()).toBe(true);
  mount.transcript.node.onMouseDown({ type: "down", button: 2, x: 2, y: 2 });
  expect(mount.contextMenu.isVisible()).toBe(true);
  expect(mount.picker.isVisible()).toBe(false);
  expect(store.get().ui.paletteOpen).toBe(false);
  mount.composer.activateHint("history");
  expect(mount.contextMenu.isVisible()).toBe(false);
  expect(mount.historySearch.isOpen()).toBe(true);
  mount.togglePalette();
  expect(mount.historySearch.isOpen()).toBe(false);
  expect(mount.picker.isVisible()).toBe(true);
  expect(store.get().ui.paletteOpen).toBe(true);
  mount.destroy();
});
