import type { AppState } from "../state/reducer";
import type { Store } from "../state/store";
import { ApprovalModalWidget } from "./widgets/ApprovalModal";
import { ComposerWidget } from "./widgets/Composer";
import { ContextMenuWidget } from "./widgets/ContextMenu";
import { DividerWidget } from "./widgets/Divider";
import { ErrorBarWidget } from "./widgets/ErrorBar";
import { HistorySearchWidget } from "./widgets/HistorySearch";
import { MentionMenuWidget } from "./widgets/MentionMenu";
import { PaletteWidget } from "./widgets/Palette";
import { RailWidget } from "./widgets/Rail";
import { buildSplash } from "./widgets/Splash";
import { StatusBarWidget } from "./widgets/StatusBar";
import { TranscriptWidget } from "./widgets/Transcript";
import { copyLastAssistant, copyToClipboard } from "./clipboard";
import type { KeyBinding } from "./keymap";
import { saveComposerHistory } from "./historyStore";
import { applyCandidate, detectMention, pickCandidates } from "./mentions";
import { createAnimator } from "./animations";
import { FocusStack } from "./focus";
import { makeBox } from "./layout";
import type { RendererHost } from "./renderer";
import { resolveTheme } from "./theme";

export type MountOptions = {
  keymap?: KeyBinding[];
  composerHistory?: string[];
};

export type MountHandle = {
  refresh: () => void;
  composer: ComposerWidget;
  palette: PaletteWidget;
  approval: ApprovalModalWidget;
  transcript: TranscriptWidget;
  rail: RailWidget;
  statusBar: StatusBarWidget;
  historySearch: HistorySearchWidget;
  contextMenu: ContextMenuWidget;
  mentionMenu: MentionMenuWidget;
  focus: FocusStack;
  keymap: KeyBinding[];
  toggleRail: () => void;
  togglePalette: () => void;
  openHistorySearch: () => void;
  destroy: () => void;
};

export function mountApp(host: RendererHost, store: Store, options: MountOptions = {}): MountHandle {
  const theme = resolveTheme(store.get().ui.theme);
  const opentui = host.opentui;
  const ctx = host.ctx;
  const root = host.root;
  const animator = createAnimator(opentui);

  const shell = makeBox(opentui, ctx, {
    flexDirection: "column",
    flexGrow: 1,
    width: "100%",
    height: "100%",
    backgroundColor: theme.background,
  });
  const main = makeBox(opentui, ctx, {
    flexDirection: "row",
    flexGrow: 1,
    minHeight: 6,
    overflow: "hidden",
  });

  const transcript = new TranscriptWidget(opentui, ctx, theme);
  const rail = new RailWidget(opentui, ctx, theme);
  const divider = new DividerWidget(opentui, ctx, theme);
  const composer = new ComposerWidget(opentui, ctx, theme);
  const palette = new PaletteWidget(opentui, ctx, theme);
  const approval = new ApprovalModalWidget(opentui, ctx, theme);
  const statusBar = new StatusBarWidget(opentui, ctx, theme);
  const errorBar = new ErrorBarWidget(opentui, ctx, theme);
  const splash = buildSplash(opentui, ctx, theme);
  const contextMenu = new ContextMenuWidget(opentui, ctx, theme);
  const historySearch = new HistorySearchWidget(opentui, ctx, theme);
  const mentionMenu = new MentionMenuWidget(opentui, ctx, theme);
  for (const entry of options.composerHistory ?? []) composer.pushHistory(entry);
  divider.setListener((width) => {
    if (rail.node && "width" in rail.node) rail.node.width = width;
    host.requestRender();
  });

  // Transcript column with splash at top.
  const transcriptColumn = makeBox(opentui, ctx, {
    flexDirection: "column",
    flexGrow: 1,
    minWidth: 0,
    overflow: "hidden",
  });
  transcriptColumn.add?.(splash);
  transcriptColumn.add?.(transcript.node);

  main.add?.(transcriptColumn);
  main.add?.(divider.node);
  main.add?.(rail.node);

  shell.add?.(main);
  shell.add?.(errorBar.node);
  shell.add?.(approval.node);
  shell.add?.(palette.node);
  shell.add?.(composer.node);
  shell.add?.(statusBar.node);
  shell.add?.(contextMenu.node);
  shell.add?.(historySearch.node);
  shell.add?.(mentionMenu.node);

  root?.add?.(shell);

  // Right-click anywhere in the transcript or rail surfaces opens the context menu.
  const openContextMenuFor = (kind: "transcript" | "rail" | "composer", x: number, y: number) => {
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
        // Bubble to keymap layer — emit a synthetic command via store flag.
        store.set({ ...state, errors: [...state.errors, "Stop requested via menu."] });
      }
      host.requestRender();
    });
  };

  const focus = new FocusStack();
  focus.registerCycle([
    { id: "composer", focus: () => composer.focus(), blur: () => composer.blur() },
    { id: "transcript", focus: () => transcript.node?.focus?.(), blur: () => transcript.node?.blur?.() },
    { id: "rail", focus: () => rail.node?.focus?.(), blur: () => rail.node?.blur?.() },
  ]);

  // Wire right-click only — left-click focus and scroll-wheel are handled
  // natively by the renderer (autoFocus on click + ScrollBox's built-in
  // scroll/drag-select + Textarea's built-in cursor positioning). Setting an
  // outer-Box handler that touches focus interferes with that flow.
  const onRightClickFor = (menuKind: "transcript" | "rail" | "composer") => (event: any) => {
    if (event?.type !== "down" || event?.button !== 2) return;
    openContextMenuFor(menuKind, event?.x ?? 0, event?.y ?? 0);
    host.requestRender();
  };
  if (transcript.node && "onMouseDown" in transcript.node) transcript.node.onMouseDown = onRightClickFor("transcript");
  if (rail.node && "onMouseDown" in rail.node) rail.node.onMouseDown = onRightClickFor("rail");
  if (composer.node && "onMouseDown" in composer.node) composer.node.onMouseDown = onRightClickFor("composer");

  // Keep the FocusStack in sync with whatever the renderer auto-focuses on
  // click. The deepest focusable Renderable (textarea, scrollbox, select, …)
  // becomes the focused target — walk up to figure out which lane it's in.
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
      } else if (renderable === rail.node || isWithin(rail.node, renderable)) {
        focus.focusById("rail");
      } else if (renderable === composer.node || isWithin(composer.node, renderable)) {
        focus.focusById("composer");
      }
    });
  }

  const toggleRail = () => {
    const state = store.get();
    const next = !state.ui.rightRail;
    if (next) {
      if (rail.node && "visible" in rail.node) rail.node.visible = true;
      animator.fadeIn(rail.node, { duration: 180 });
    } else {
      animator.fadeOut(rail.node, { duration: 140 });
    }
    store.set({ ...state, ui: { ...state.ui, rightRail: next } });
  };
  const togglePalette = () => {
    const state = store.get();
    const next = !state.ui.paletteOpen;
    if (next) {
      animator.fadeIn(palette.node, { duration: 160 });
    } else {
      animator.fadeOut(palette.node, { duration: 120 });
    }
    store.set({ ...state, ui: { ...state.ui, paletteOpen: next } });
  };
  const openHistorySearch = () => {
    historySearch.open(composer.historyList(), (value) => {
      composer.setValue(value);
      composer.focus();
    });
    animator.fadeIn(historySearch.node, { duration: 160 });
    host.requestRender();
  };

  // Splash pulse for empty state.
  if (splash) animator.pulse(splash, { duration: 1200 });

  let pending = false;
  const doRefresh = (): void => {
    pending = false;
    const state = store.get();
    transcript.setShowReasoning(state.ui.showReasoning);
    transcript.setTurns(state.activeSession?.turns ?? []);
    rail.update(state);
    statusBar.update(state);
    errorBar.setErrors(state.errors);
    approval.setApproval(state.activeSession?.pendingApproval ?? null);
    if (state.activeSession?.pendingApproval) {
      focus.push({ id: "approval", focus: () => approval.node?.focus?.(), blur: () => approval.node?.blur?.() });
      animator.fadeIn(approval.node, { duration: 180, from: 0.4 });
    }
    if (rail.node && "visible" in rail.node) rail.node.visible = state.ui.rightRail;
    if (rail.node && "enableLayout" in rail.node) rail.node.enableLayout = state.ui.rightRail;
    if (divider.node && "visible" in divider.node) divider.node.visible = state.ui.rightRail;
    if (divider.node && "enableLayout" in divider.node) divider.node.enableLayout = state.ui.rightRail;
    if (state.ui.paletteOpen) palette.show();
    else palette.hide();
    const empty = (state.activeSession?.turns.length ?? 0) === 0;
    if (splash && "visible" in splash) splash.visible = empty;
    if (splash && "enableLayout" in splash) splash.enableLayout = empty;
    host.requestRender();
  };

  const refresh = (): void => {
    if (host.kind === "headless") {
      doRefresh();
      return;
    }
    if (pending) return;
    pending = true;
    queueMicrotask(doRefresh);
  };

  const unsubscribe = store.subscribe(refresh);
  doRefresh();

  const destroy = (): void => {
    unsubscribe();
  };

  // Persist composer history on submit.
  const submitWatcher = () => {
    saveComposerHistory(composer.historyList());
  };
  composer.onSubmitWatcher = submitWatcher;

  // Mention detection — fires every composer change.
  composer.setOnChange((value, cursor) => {
    const detection = detectMention(value, cursor);
    if (!detection) {
      mentionMenu.hide();
      const s = store.get();
      if (s.mention.trigger) store.set({ ...s, mention: { trigger: null, query: "", index: 0 } });
      return;
    }
    const s = store.get();
    const candidates = pickCandidates(detection, s.workspaceFiles, s.skills);
    mentionMenu.open(detection, candidates, (candidate) => {
      const next = applyCandidate(value, detection, candidate);
      composer.setValue(next);
      mentionMenu.hide();
      composer.focus();
      const cur = store.get();
      store.set({ ...cur, mention: { trigger: null, query: "", index: 0 } });
    });
    store.set({ ...s, mention: { trigger: detection.trigger, query: detection.query, index: 0 } });
  });

  return {
    refresh,
    composer,
    palette,
    approval,
    transcript,
    rail,
    statusBar,
    historySearch,
    contextMenu,
    mentionMenu,
    focus,
    keymap: options.keymap ?? [],
    toggleRail,
    togglePalette,
    openHistorySearch,
    destroy,
  };
}

export function snapshotForTests(state: AppState): string {
  // Plain-text projection — kept as the snapshot used by unit tests.
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
