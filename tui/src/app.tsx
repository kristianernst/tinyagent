// Public entry surface kept stable for unit tests and external callers.
// New code lives under controller/ and ui/; this module re-exports + hosts
// the legacy interactive loop and the run-app driver used by main.ts.

import { parseCommandInput } from "./commands";
import { TinyAgentClient } from "./backend/client";
import { connectBackend } from "./backend/connect";
import { spawnBackend, type SpawnedBackend } from "./backend/spawn";
import { handleCommand } from "./controller/commands";
import { appendError } from "./controller/errors";
import { startRunTask, type ActiveRun } from "./controller/runs";
import { renderRootShell } from "./components/RootShell";
import {
  createSession,
  emptyState,
  type AppState,
} from "./state/reducer";
import { Store } from "./state/store";
import { createRendererHost } from "./ui/renderer";
import { mountApp, type MountHandle } from "./ui/mount";
import { applyUserThemes } from "./ui/themeLoader";
import { loadUserKeymap } from "./ui/keymapLoader";
import { loadComposerHistory, saveComposerHistory } from "./ui/historyStore";
import { loadSettings } from "./ui/widgets/SettingsWidget";

export { handleCommand, startRunTask };
export type { ActiveRun };

export type AppOptions = {
  server?: string;
  workspace?: string;
  provider?: string;
  model?: string;
  profile?: string;
  approvalMode?: string;
  task?: string;
};

export async function runApp(options: AppOptions): Promise<number> {
  let spawned: SpawnedBackend | null = null;
  const client = options.server
    ? await connectBackend(options.server)
    : await spawnBackend({
        workspace: options.workspace ?? ".",
        provider: options.provider ?? "fake",
        model: options.model,
        profile: options.profile,
        approvalMode: options.approvalMode,
      }).then((backend) => {
        spawned = backend;
        return connectBackend(backend.baseUrl);
      });

  applyUserThemes();
  const customKeymap = loadUserKeymap();
  const composerHistory = loadComposerHistory();
  const store = new Store(await initializeState(client));
  const host = await createRendererHost();
  const mount = mountApp(host, store, { keymap: customKeymap, composerHistory });
  const renderState = (_seq?: number) => mount.refresh();

  try {
    renderState();
    if (options.task) {
      const active = await startRunTask(client, store, options.task, renderState);
      await active.done;
      renderState();
      return store.get().phase === "failed" ? 1 : 0;
    }
    if (host.kind === "interactive") {
      await interactiveLoop(client, store, mount, host, renderState);
    } else if (process.stdin.isTTY) {
      await readlineLoop(client, store, renderState);
    } else {
      return 0;
    }
    return 0;
  } finally {
    mount.destroy();
    host.stop();
    spawned?.stop();
  }
}

async function initializeState(client: TinyAgentClient): Promise<AppState> {
  const workspaces = await client.listWorkspaces();
  const activeWorkspaceId = workspaces[0]?.workspace_id ?? null;
  const sessions = activeWorkspaceId ? await client.listConversations(activeWorkspaceId).catch(() => []) : [];
  const workspaceFiles = activeWorkspaceId ? await client.workspaceFiles(activeWorkspaceId).catch(() => []) : [];
  const git = activeWorkspaceId ? await client.gitStatus(activeWorkspaceId).catch(() => null) : null;
  const updateStatus = await client.updateStatus().catch(() => null);
  const persistedSettings = loadSettings();
  const base = emptyState();
  return {
    ...base,
    workspaces,
    activeWorkspaceId,
    workspaceFiles,
    sessions,
    activeSession: { ...createSession(sessions[0]?.conversation_id ?? "local"), git },
    updatePanel: updateStatus
      ? { status: "ready", result: updateStatus, lastAction: "auto-check", error: "" }
      : base.updatePanel,
    settings: { ...base.settings, ...persistedSettings, dirty: false },
    ui: {
      ...base.ui,
      theme: persistedSettings.theme ?? base.ui.theme,
      spinner: persistedSettings.spinner ?? base.ui.spinner,
      showReasoning: persistedSettings.showReasoning ?? base.ui.showReasoning,
      diffView: persistedSettings.diffView ?? base.ui.diffView,
      rightRail: persistedSettings.rightRail ?? base.ui.rightRail,
    },
  };
}

async function interactiveLoop(
  client: TinyAgentClient,
  store: Store,
  mount: MountHandle,
  host: { on: (event: string, handler: (...args: any[]) => void) => void; off: (event: string, handler: (...args: any[]) => void) => void; requestRender: () => void; opentui: any },
  render: (tick?: number) => void,
): Promise<void> {
  let activeRun: ActiveRun | null = null;
  let resolveDone: (() => void) | null = null;
  // Set by overlay commit paths (mention, palette) so the trailing Enter
  // doesn't trigger a real message submit on the textarea afterwards.
  let suppressNextSubmit = false;
  const done = new Promise<void>((resolve) => {
    resolveDone = resolve;
  });

  mount.composer.setOnSubmit(async (value) => {
    if (suppressNextSubmit) {
      suppressNextSubmit = false;
      return;
    }
    // Swallow submits while an overlay is consuming Enter.
    if (mount.mentionMenu.isVisible() || mount.palette.isVisible() || mount.historySearch.isOpen()) {
      return;
    }
    const trimmed = value.trim();
    if (!trimmed) return;
    if (trimmed === "/quit" || trimmed === "/exit") {
      resolveDone?.();
      return;
    }
    const parsed = parseCommandInput(trimmed);
    if (parsed) {
      activeRun = await handleCommand(client, store, parsed, activeRun, render);
      render();
      return;
    }
    if (activeRun) {
      appendError(store, "A run is already active. Use /stop before starting another.");
      render();
      return;
    }
    activeRun = await startRunTask(client, store, trimmed, render);
    activeRun.done.finally(() => {
      activeRun = null;
      render();
    });
    render();
  });

  mount.palette.setOnSelect(async (id) => {
    mount.palette.hide();
    activeRun = await handleCommand(client, store, { id, args: [] }, activeRun, render);
    render();
  });

  mount.approval.setOnDecide(async (decision, id) => {
    activeRun = await handleCommand(
      client,
      store,
      { id: decision === "approved" ? "approve" : "deny", args: id ? [id] : [] },
      activeRun,
      render,
    );
    render();
  });

  // Global key handler — interrupt, palette, etc.
  const keyHandler = async (key: { name?: string; ctrl?: boolean; meta?: boolean; shift?: boolean; sequence?: string }) => {
    const name = (key.name ?? key.sequence ?? "").toLowerCase();

    // Mention menu (/, @, $) hijacks navigation while open. Composer keeps
    // focus so the user can keep typing to filter; only nav keys are routed.
    if (mount.mentionMenu.isVisible()) {
      if (name === "up") {
        mount.mentionMenu.moveUp();
        render();
        return;
      }
      if (name === "down") {
        mount.mentionMenu.moveDown();
        render();
        return;
      }
      if (name === "tab" || name === "return" || name === "enter") {
        if (mount.mentionMenu.commit()) {
          suppressNextSubmit = true;
          render();
          return;
        }
      }
      if (name === "escape") {
        mount.mentionMenu.hide();
        render();
        return;
      }
      // Any other key falls through to the textarea so the user can continue typing.
    }

    // Palette is a real modal — its select holds focus, so arrows work natively.
    // We just need to handle Escape and the outer toggle here.
    if (mount.palette.isVisible()) {
      if (name === "escape") {
        mount.togglePalette();
        render();
        return;
      }
      if (name === "return" || name === "enter") {
        if (mount.palette.commit()) {
          suppressNextSubmit = true;
          render();
          return;
        }
      }
      if (name === "up") {
        mount.palette.moveUp();
        render();
        return;
      }
      if (name === "down") {
        mount.palette.moveDown();
        render();
        return;
      }
    }

    if (key.ctrl && name === "c") {
      if (activeRun) {
        activeRun.abort.abort();
        await handleCommand(client, store, { id: "stop", args: [] }, activeRun, render);
        render();
        return;
      }
      resolveDone?.();
      return;
    }
    if (key.ctrl && (name === "k" || name === "p")) {
      mount.togglePalette();
      return;
    }
    if (key.ctrl && name === "r") {
      mount.openHistorySearch();
      return;
    }
    if (key.ctrl && name === "b") {
      mount.toggleRail();
      return;
    }
    if (mount.historySearch.isOpen()) {
      if (name === "escape") {
        mount.historySearch.close();
        return;
      }
      if (name === "return" || name === "enter") {
        mount.historySearch.commit();
        suppressNextSubmit = true;
        return;
      }
      if (name === "backspace") {
        mount.historySearch.backspace();
        return;
      }
      if (key.ctrl && name === "r") {
        mount.historySearch.cycle();
        return;
      }
      if (key.sequence && key.sequence.length === 1 && !key.ctrl && !key.meta) {
        mount.historySearch.appendChar(key.sequence);
        return;
      }
    }
    if (key.ctrl && name === "d") {
      activeRun = await handleCommand(client, store, { id: "diff", args: [] }, activeRun, render);
      render();
      return;
    }
    if (key.ctrl && name === "u") {
      activeRun = await handleCommand(client, store, { id: "usage", args: [] }, activeRun, render);
      render();
      return;
    }
    if (name === "tab" && !key.shift) {
      mount.focus.cycleNext();
      return;
    }
    if (name === "tab" && key.shift) {
      mount.focus.cyclePrevious();
      return;
    }
  };
  host.on?.("keypress", keyHandler);

  mount.composer.focus();
  await done;
  host.off?.("keypress", keyHandler);
}

async function readlineLoop(
  client: TinyAgentClient,
  store: Store,
  render: (tick?: number) => void,
): Promise<void> {
  const readline = await import("node:readline/promises");
  const terminal = readline.createInterface({ input: process.stdin, output: process.stdout });
  let activeRun: ActiveRun | null = null;
  const clearWhenDone = (run: ActiveRun) => {
    run.done.finally(() => {
      if (activeRun === run) activeRun = null;
      render();
    });
  };
  try {
    while (true) {
      const input = await terminal.question("> ");
      const trimmed = input.trim();
      if (!trimmed) continue;
      if (trimmed === "/quit" || trimmed === "/exit") break;
      const command = parseCommandInput(trimmed);
      if (command) {
        activeRun = await handleCommand(client, store, command, activeRun, render);
        render();
        continue;
      }
      if (activeRun) {
        appendError(store, "A run is already active. Use /stop before starting another.");
        render();
        continue;
      }
      activeRun = await startRunTask(client, store, trimmed, render);
      clearWhenDone(activeRun);
      render();
    }
  } finally {
    terminal.close();
    activeRun?.abort.abort();
  }
}

// Compat: legacy test snapshot path remains.
export { renderRootShell };
