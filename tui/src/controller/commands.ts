import type { TinyAgentClient } from "../backend/client";
import { applyLocalCommand, type ParsedCommand } from "../commands";
import { createSession, sessionFromConversationTurns } from "../state/reducer";
import type { Store } from "../state/store";
import { appendError, safeClientAction } from "./errors";
import { runEvalCommand } from "./eval";
import { forkReplay, loadReplay, rewindReplay } from "./replay";
import { refreshSessions, refreshWorkspaceSurface, resolvePendingApproval, type ActiveRun } from "./runs";
import { runExtensionsCommand } from "./extensions";
import { runSettingsCommand } from "./settings";
import { runSkillsCommand } from "./skills";
import { runUpdateCommand } from "./update";

const newConversationId = () => `conv_${crypto.randomUUID().replaceAll("-", "")}`;

export async function handleCommand(
  client: TinyAgentClient,
  store: Store,
  command: ParsedCommand,
  activeRun: ActiveRun | null,
  render: (tick?: number) => void = () => {},
): Promise<ActiveRun | null> {
  if (command.id === "stop") {
    const runId = activeRun?.runId ?? store.get().activeSession?.runId;
    if (!runId) return activeRun;
    await safeClientAction(store, () =>
      client.cancel(runId, activeRun?.workspaceId ?? store.get().activeWorkspaceId ?? undefined, "tui_stop"),
    );
    render();
    return activeRun;
  }
  if (command.id === "approve" || command.id === "deny") {
    await resolvePendingApproval(client, store, command.id === "approve" ? "approved" : "denied", command.args[0]);
    render();
    return activeRun;
  }
  if (command.id === "sessions") {
    await refreshSessions(client, store);
    store.set(applyLocalCommand(store.get(), command.id));
    return activeRun;
  }
  if (command.id === "context" || command.id === "diff") {
    await refreshWorkspaceSurface(client, store);
    store.set(applyLocalCommand(store.get(), command.id));
    return activeRun;
  }
  if (command.id === "replay") {
    await loadReplay(client, store, command.args[0] ?? activeRun?.runId ?? store.get().activeSession?.runId ?? "");
    store.set(applyLocalCommand(store.get(), command.id));
    return activeRun;
  }
  if (command.id === "rewind") {
    await rewindReplay(client, store, command.args[0], activeRun);
    store.set(applyLocalCommand(store.get(), command.id));
    return activeRun;
  }
  if (command.id === "fork") {
    await forkReplay(client, store, command.args, activeRun);
    store.set(applyLocalCommand(store.get(), command.id));
    return activeRun;
  }
  if (command.id === "review") {
    if (!store.get().replay && (activeRun?.runId || store.get().activeSession?.runId)) {
      await loadReplay(client, store, activeRun?.runId ?? store.get().activeSession?.runId ?? "");
    }
    store.set(applyLocalCommand(store.get(), command.id));
    return activeRun;
  }
  if (command.id === "eval") {
    await runEvalCommand(client, store, command.args[0]);
    store.set(applyLocalCommand(store.get(), command.id));
    return activeRun;
  }
  if (command.id === "skills") {
    await runSkillsCommand(client, store, command.args);
    store.set(applyLocalCommand(store.get(), command.id));
    return activeRun;
  }
  if (command.id === "update") {
    await runUpdateCommand(client, store, command.args, Boolean(activeRun));
    store.set(applyLocalCommand(store.get(), command.id));
    return activeRun;
  }
  if (command.id === "settings") {
    runSettingsCommand(store, command.args);
    return activeRun;
  }
  if (command.id === "extensions") {
    await runExtensionsCommand(client, store);
    return activeRun;
  }
  if (command.id === "new") {
    if (activeRun) {
      appendError(store, "Stop the active run before starting a new session.");
      return activeRun;
    }
    const state = store.get();
    store.set({
      ...state,
      activeSession: createSession(newConversationId()),
      phase: "idle",
      errors: [],
      ui: { ...state.ui, activePanel: "transcript" },
    });
    return null;
  }
  if (command.id === "resume") {
    if (activeRun) {
      appendError(store, "Stop the active run before resuming another session.");
      return activeRun;
    }
    await refreshSessions(client, store);
    const conversationId = command.args[0] ?? store.get().sessions[0]?.conversation_id;
    if (conversationId) await resumeConversation(client, store, conversationId);
    else store.set(applyLocalCommand(store.get(), command.id));
    return activeRun;
  }
  store.set(applyLocalCommand(store.get(), command.id));
  return activeRun;
}

async function resumeConversation(client: TinyAgentClient, store: Store, conversationId: string): Promise<void> {
  const workspaceId = store.get().activeWorkspaceId ?? undefined;
  const turns = await client.conversationTurns(conversationId, workspaceId);
  const state = store.get();
  store.set({
    ...state,
    activeSession: sessionFromConversationTurns(conversationId, turns),
    ui: { ...state.ui, activePanel: "transcript" },
  });
}
