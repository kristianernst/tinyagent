import type { AppState } from "../state/reducer";
import type { Store } from "../state/store";
import type { CommandId } from "../commands";
import { ApprovalModalWidget } from "./widgets/ApprovalModal";
import { ChromeBarWidget, type ChromeAction } from "./widgets/ChromeBar";
import { ComposerWidget } from "./widgets/Composer";
import { ContextMenuWidget } from "./widgets/ContextMenu";
import { ErrorBarWidget } from "./widgets/ErrorBar";
import { HistorySearchWidget } from "./widgets/HistorySearch";
import { PickerWidget } from "./widgets/Picker";
import { RailWidget } from "./widgets/Rail";
import { TranscriptWidget } from "./widgets/Transcript";
import { copyLastAssistant, copyToClipboard } from "./clipboard";
import type { KeyBinding } from "./keymap";
import { saveComposerHistory } from "./historyStore";
import { applyCandidate, detectMention, pickCandidates } from "./mentions";
import { createAnimator } from "./animations";
import { FRAME_MS, motionMs } from "../design/primitives";
import { FocusStack } from "./focus";
import { makeBox } from "./layout";
import type { RendererHost } from "./renderer";
import { resolveTheme } from "./theme";

export type MountOptions = {
  keymap?: KeyBinding[];
  composerHistory?: string[];
};

// Minimal back-compat shim: app.tsx still calls `mount.palette.setOnSelect()`
// and `mount.mentionMenu.{isVisible,moveUp,...}`. Both surfaces are now the
// same PickerWidget; this object proxies the old command-palette API.
export type PaletteShim = {
  show(): void;
  hide(): void;
  isVisible(): boolean;
  setOnSelect(handler: (id: CommandId) => void): void;
  commit(): boolean;
  moveUp(): void;
  moveDown(): void;
};

export type MountHandle = {
  refresh: () => void;
  composer: ComposerWidget;
  picker: PickerWidget;
  palette: PaletteShim;
  mentionMenu: PickerWidget;
  approval: ApprovalModalWidget;
  transcript: TranscriptWidget;
  rail: RailWidget;
  chromeBar: ChromeBarWidget;
  historySearch: HistorySearchWidget;
  contextMenu: ContextMenuWidget;
  focus: FocusStack;
  keymap: KeyBinding[];
  toggleRail: () => void;
  closePanelOverlay: () => void;
  togglePalette: () => void;
  openHistorySearch: () => void;
  setOnSlashCommand: (handler: (id: CommandId) => void) => void;
  destroy: () => void;
};

export function mountApp(host: RendererHost, store: Store, options: MountOptions = {}): MountHandle {
  const theme = resolveTheme(store.get().ui.theme);
  const opentui = host.opentui;
  const ctx = host.ctx;
  const root = host.root;
  const animator = createAnimator(opentui);

  // ── Shell ────────────────────────────────────────────────────────────────
  // Top-to-bottom flow per DESIGN_TOKENS.md §4.1: chrome bar · transcript · composer.
  // No persistent rail, no status footer, no splash, no header row inside the
  // transcript surface.
  const shell = makeBox(opentui, ctx, {
    flexDirection: "column",
    flexGrow: 1,
    width: "100%",
    height: "100%",
    backgroundColor: theme.background,
  });

  // ── Widgets ──────────────────────────────────────────────────────────────
  const chromeBar = new ChromeBarWidget(opentui, ctx, theme);
  const transcript = new TranscriptWidget(opentui, ctx, theme);
  const composer = new ComposerWidget(opentui, ctx, theme);
  const picker = new PickerWidget(opentui, ctx, theme);
  const approval = new ApprovalModalWidget(opentui, ctx, theme);
  const errorBar = new ErrorBarWidget(opentui, ctx, theme);
  const contextMenu = new ContextMenuWidget(opentui, ctx, theme);
  const historySearch = new HistorySearchWidget(opentui, ctx, theme);

  // Former rail panels now mount as a Paper-style right-side overlay. The
  // persisted `rightRail` setting stays disabled; panel visibility is driven
  // by `ui.activePanel` so commands can open focused surfaces without changing
  // the root column layout.
  const rail = new RailWidget(opentui, ctx, theme);

  for (const entry of options.composerHistory ?? []) composer.pushHistory(entry);

  // ── Layout ──────────────────────────────────────────────────────────────
  shell.add?.(chromeBar.node);
  shell.add?.(transcript.node);
  shell.add?.(composer.node);

  // Overlays sit on top of the shell column via absolute positioning + zIndex.
  // Order matters only for stable click hit-testing; visual stack is z-driven.
  shell.add?.(errorBar.node);
  shell.add?.(rail.node);
  shell.add?.(picker.node);
  shell.add?.(approval.node);
  shell.add?.(historySearch.node);
  shell.add?.(contextMenu.node);

  root?.add?.(shell);

  // ── Right-click → context menu ──────────────────────────────────────────
  const openContextMenuFor = (kind: "transcript" | "rail" | "composer", x: number, y: number) => {
    closeTransientOverlays("context");
    const items = contextMenuItems(kind);
    contextMenu.showAt(x, y, items, async (value) => {
      const state = store.get();
      if (value === "copy-last") await copyLastAssistant(state.activeSession?.turns);
      else if (value === "copy-conv") {
        const text = (state.activeSession?.turns ?? []).map((turn) => `› ${turn.user}\n${turn.assistant}`).join("\n\n");
        await copyToClipboard(text);
      } else if (value === "copy-diff") {
        await copyToClipboard(state.activeSession?.diff?.text ?? "");
      } else if (value === "stop-run") {
        store.set({ ...state, errors: [...state.errors, "Stop requested via menu."] });
      }
      host.requestRender();
    });
  };

  const focus = new FocusStack();
  focus.registerCycle([
    { id: "composer", focus: () => composer.focus(), blur: () => composer.blur() },
    { id: "transcript", focus: () => transcript.node?.focus?.(), blur: () => transcript.node?.blur?.() },
  ]);

  const onRightClickFor = (menuKind: "transcript" | "rail" | "composer") => (event: any) => {
    if (event?.type !== "down" || event?.button !== 2) return;
    openContextMenuFor(menuKind, event?.x ?? 0, event?.y ?? 0);
    host.requestRender();
  };
  if (transcript.node) transcript.node.onMouseDown = onRightClickFor("transcript");
  if (rail.node) rail.node.onMouseDown = onRightClickFor("rail");
  if (composer.node) composer.node.onMouseDown = onRightClickFor("composer");

  const openChromeAction = (action: ChromeAction) => {
    const state = store.get();
    if (action === "approval") {
      if (state.activeSession?.pendingApproval) {
        approval.node?.focus?.();
      }
      host.requestRender();
      return;
    }
    store.set({ ...state, ui: { ...state.ui, rightRail: false, activePanel: action } });
  };
  chromeBar.setOnAction(openChromeAction);

  if (host.kind === "interactive") {
    const isWithin = (root: any, node: any): boolean => {
      if (!node || !root) return false;
      let cur: any = node;
      while (cur) {
        if (cur === root) return true;
        cur = cur.parent;
      }
      return false;
    };
    host.on("focused_renderable", (renderable: any) => {
      if (!renderable) return;
      if (renderable === transcript.node || isWithin(transcript.node, renderable)) {
        focus.focusById("transcript");
      } else if (renderable === composer.node || isWithin(composer.node, renderable)) {
        focus.focusById("composer");
      }
    });
  }

  // ── Palette shim (command palette mode of picker) ───────────────────────
  let paletteSelectHandler: ((id: CommandId) => void) | null = null;
  let slashCommandHandler: ((id: CommandId) => void) | null = null;
  const palette: PaletteShim = {
    show: () => {
      if (paletteSelectHandler) picker.openCommandPalette(paletteSelectHandler);
      else picker.openCommandPalette(() => {});
    },
    hide: () => picker.hide(),
    isVisible: () => picker.isVisible(),
    setOnSelect: (handler) => {
      paletteSelectHandler = handler;
    },
    commit: () => picker.commit(),
    moveUp: () => picker.moveUp(),
    moveDown: () => picker.moveDown(),
  };

  const toggleRail = () => {
    const state = store.get();
    store.set({ ...state, ui: { ...state.ui, rightRail: false, activePanel: "sessions" } });
  };
  const closePanelOverlay = () => {
    const state = store.get();
    rail.hide();
    store.set({ ...state, ui: { ...state.ui, rightRail: false, activePanel: "transcript" } });
  };
  const closePickerOverlay = () => {
    picker.hide();
    const state = store.get();
    if (state.ui.paletteOpen) store.set({ ...state, ui: { ...state.ui, paletteOpen: false } });
  };
  const closeTransientOverlays = (keep?: "picker" | "history" | "context") => {
    if (keep !== "picker") closePickerOverlay();
    if (keep !== "history") historySearch.close();
    if (keep !== "context") contextMenu.hide();
  };
  const togglePalette = () => {
    const state = store.get();
    const next = !state.ui.paletteOpen;
    if (next) {
      closeTransientOverlays("picker");
      palette.show();
    } else {
      palette.hide();
    }
    store.set({ ...state, ui: { ...state.ui, paletteOpen: next } });
  };
  const openHistorySearch = () => {
    closeTransientOverlays("history");
    historySearch.open(composer.historyList(), (value) => {
      composer.setValue(value);
      composer.focus();
    });
    host.requestRender();
  };
  composer.setOnHintAction((action) => {
    if (action === "history") {
      openHistorySearch();
      return;
    }
    closeTransientOverlays("picker");
    composer.insertTrigger(action);
    host.requestRender();
  });

  // ── Refresh: frame-gated (DESIGN_TOKENS.md §6.3) ────────────────────────
  // Bursts of streaming chunks coalesce into a single paint per animation
  // frame. queueMicrotask was already used, but it can fire multiple times
  // per frame; we add a requestAnimationFrame-style gate so the renderer
  // really does ≤ 1 paint per ~33 ms tick.
  let pending = false;
  let scheduledTime = 0;

  const doRefresh = (): void => {
    pending = false;
    scheduledTime = 0;
    let state = store.get();
    const pendingApproval = state.activeSession?.pendingApproval ?? null;
    const modalApproval = state.phase === "approval" ? pendingApproval : null;
    const panelOpen = state.ui.activePanel !== "transcript";
    if (panelOpen || modalApproval) {
      historySearch.close();
      contextMenu.hide();
      if (state.ui.paletteOpen) {
        state = { ...state, ui: { ...state.ui, paletteOpen: false } };
        store.set(state);
      }
    }
    chromeBar.update(state, host.width);
    composer.setViewportWidth(host.width);
    transcript.setViewportWidth(host.width);
    rail.setViewportWidth(host.width);
    transcript.setShowReasoning(state.ui.showReasoning);
    transcript.setTurns(state.activeSession?.turns ?? []);
    transcript.setDiff(panelOpen ? null : (state.activeSession?.diff ?? null));
    rail.update(state);
    errorBar.setErrors(state.errors);
    approval.setBackdropLines(modalApproval ? approvalBackdropLines(state) : []);
    approval.setApproval(modalApproval);
    setRenderableVisible(composer.node, !modalApproval && !panelOpen);
    if (modalApproval) {
      focus.push({ id: "approval", focus: () => approval.node?.focus?.(), blur: () => approval.node?.blur?.() });
      animator.fadeIn(approval.node, { duration: motionMs.slow, from: 0.4 });
    }
    if (panelOpen || modalApproval) {
      picker.hide();
    } else if (state.ui.paletteOpen) {
      palette.show();
    }
    host.requestRender();
  };

  const refresh = (): void => {
    if (host.kind === "headless") {
      doRefresh();
      return;
    }
    if (pending) return;
    pending = true;
    const now = Date.now();
    const since = scheduledTime ? now - scheduledTime : Infinity;
    if (since >= FRAME_MS) {
      scheduledTime = now;
      queueMicrotask(doRefresh);
    } else {
      scheduledTime = now;
      setTimeout(doRefresh, Math.max(1, FRAME_MS - since));
    }
  };

  const unsubscribe = store.subscribe(refresh);
  doRefresh();

  const destroy = (): void => {
    unsubscribe();
  };

  const submitWatcher = () => {
    saveComposerHistory(composer.historyList());
  };
  composer.onSubmitWatcher = submitWatcher;

  // ── Mention detection drives the unified picker ─────────────────────────
  composer.setOnChange((value, cursor) => {
    const detection = detectMention(value, cursor);
    if (!detection) {
      // Only hide the picker if it's in mention mode. Command-palette mode
      // (opened explicitly via Ctrl+K) shouldn't dismiss when the user clears
      // the composer text.
      if (picker.isVisible() && !picker.candidateCount()) {
        picker.hide();
      } else if (picker.isVisible()) {
        // If picker was opened by typing /, @, $ and the trigger char was
        // deleted, hide it.
        picker.hide();
      }
      const s = store.get();
      if (s.mention.trigger) store.set({ ...s, mention: { trigger: null, query: "", index: 0 } });
      return;
    }
    closeTransientOverlays("picker");
    const s = store.get();
    const candidates = pickCandidates(detection, s.workspaceFiles, s.skills, { fileMetadata: s.workspaceFileMetadata });
    picker.open(detection, candidates, (candidate) => {
      if (detection.trigger === "/") {
        const id = commandIdFromCandidate(candidate.label);
        picker.hide();
        composer.focus();
        const cur = store.get();
        store.set({ ...cur, mention: { trigger: null, query: "", index: 0 } });
        if (id && slashCommandHandler) {
          composer.setValue("");
          slashCommandHandler(id);
        } else {
          composer.setValue(applyCandidate(value, detection, candidate));
        }
        return;
      }
      const next = applyCandidate(value, detection, candidate);
      composer.setValue(next);
      picker.hide();
      composer.focus();
      const cur = store.get();
      store.set({ ...cur, mention: { trigger: null, query: "", index: 0 } });
    });
    store.set({ ...s, mention: { trigger: detection.trigger, query: detection.query, index: 0 } });
  });

  return {
    refresh,
    composer,
    picker,
    palette,
    mentionMenu: picker,
    approval,
    transcript,
    rail,
    chromeBar,
    historySearch,
    contextMenu,
    focus,
    keymap: options.keymap ?? [],
    toggleRail,
    closePanelOverlay,
    togglePalette,
    openHistorySearch,
    setOnSlashCommand: (handler) => {
      slashCommandHandler = handler;
    },
    destroy,
  };
}

export function snapshotForTests(state: AppState): string {
  return JSON.stringify({ phase: state.phase, turns: state.activeSession?.turns.length ?? 0 });
}

function contextMenuItems(kind: "transcript" | "rail" | "composer") {
  const base = [
    { label: "Copy last reply", description: "Copy assistant text to clipboard", value: "copy-last" },
    { label: "Copy conversation", description: "Copy all turns as plain text", value: "copy-conv" },
  ];
  if (kind === "rail") {
    base.push({ label: "Copy diff", description: "Copy the loaded diff text", value: "copy-diff" });
  }
  if (kind === "composer") {
    base.push({ label: "Stop run", description: "Cancel any active run", value: "stop-run" });
  }
  return base;
}

function setRenderableVisible(node: any, visible: boolean): void {
  if (!node) return;
  if ("visible" in node) node.visible = visible;
  if ("enableLayout" in node) node.enableLayout = visible;
}

function approvalBackdropLines(state: AppState): string[] {
  const turn = state.activeSession?.turns.at(-1);
  if (!turn) return [];
  const lines: string[] = [];
  if (turn.user) lines.push(`  › ${fitBackdropLine(turn.user)}`);
  if (turn.reasoning.length > 0) lines.push("  ◆ thought for 4s");
  const tool = turn.tools.find((entry) => entry.status === "blocked") ?? turn.tools.at(-1);
  if (tool) {
    const label = tool.label || tool.tool;
    const detail = tool.argsSummary || tool.tool;
    lines.push(`  ⠙ ${fitBackdropLine(`${label} ${detail}`)}`);
  }
  const assistantLine = turn.assistant.split(/\n/).find((line) => line.trim());
  if (assistantLine) lines.push(`  ${fitBackdropLine(assistantLine)}`);
  if (lines.length) lines.push(`  ${"━".repeat(24)}`);
  return lines;
}

function fitBackdropLine(value: string, width = 24): string {
  const text = value.trim();
  if (text.length <= width) return text;
  return `${text.slice(0, Math.max(0, width - 1))}…`;
}

function commandIdFromCandidate(label: string): CommandId | null {
  const id = label.replace(/^\//, "") as CommandId;
  return id ? id : null;
}
