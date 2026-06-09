import type { TinyAgentClient } from "../backend/client";
import type { Store } from "../state/store";
import { metadataForWorkspaceFiles } from "../ui/fileMetadata";
import { appendError, safeClientAction } from "./errors";

export type ActiveRun = {
  runId: string;
  conversationId: string;
  workspaceId?: string;
  abort: AbortController;
  done: Promise<void>;
};

export async function startRunTask(
  client: TinyAgentClient,
  store: Store,
  task: string,
  onEvent?: (seq: number) => void,
): Promise<ActiveRun> {
  const state = store.get();
  const workspaceId = state.activeWorkspaceId ?? undefined;
  const response = await client.startRun({
    workspace_id: workspaceId,
    task,
    approval_mode: state.approvalMode,
    session_mode: state.sessionMode,
    conversation_id: state.activeSession?.conversationId,
  });
  const runId = response.run.run_id;
  const conversationId = response.run.conversation_id || state.activeSession?.conversationId || "";
  store.set({
    ...store.get(),
    provider: String(response.run.model?.provider ?? response.run.model?.name ?? state.provider),
    model: String(response.run.model?.model ?? response.run.model?.model_name ?? state.model),
    activeSession: store.get().activeSession
      ? { ...store.get().activeSession!, runId, runPath: response.run.run_path || store.get().activeSession!.runPath }
      : store.get().activeSession,
  });
  const abort = new AbortController();
  const done = client
    .streamEvents(
      runId,
      (event) => {
        if (conversationId && store.get().activeSession?.conversationId !== conversationId) return;
        store.event(event);
        onEvent?.(event.seq ?? 0);
      },
      { workspaceId, signal: abort.signal },
    )
    .then(() => refreshWorkspaceSurface(client, store).catch(() => undefined))
    .catch((error) => {
      if (abort.signal.aborted) return;
      const message = error instanceof Error ? error.message : String(error);
      appendError(store, message, { phase: "failed" });
      onEvent?.(store.get().activeSession?.lastSeq ?? 0);
    });
  return { runId, conversationId, workspaceId, abort, done };
}

export async function refreshSessions(client: TinyAgentClient, store: Store): Promise<void> {
  const workspaceId = store.get().activeWorkspaceId ?? undefined;
  const sessions = await client.listConversations(workspaceId);
  store.set({ ...store.get(), sessions });
}

export async function refreshWorkspaceSurface(client: TinyAgentClient, store: Store): Promise<void> {
  const workspaceId = store.get().activeWorkspaceId ?? undefined;
  if (!workspaceId) return;
  const [workspaceFiles, git] = await Promise.all([client.workspaceFiles(workspaceId), client.gitStatus(workspaceId)]);
  const state = store.get();
  const workspace = state.workspaces.find((item) => item.workspace_id === workspaceId);
  store.set({
    ...state,
    workspaceFiles,
    workspaceFileMetadata: metadataForWorkspaceFiles(workspace?.root, workspaceFiles),
    activeSession: state.activeSession
      ? {
          ...state.activeSession,
          git,
          diff: {
            text: git.diff,
            paths: git.files.map((file) => file.path),
            truncated: git.diffTruncated,
            omittedFiles: git.omittedFiles,
          },
        }
      : state.activeSession,
  });
}

export async function resolvePendingApproval(
  client: TinyAgentClient,
  store: Store,
  decision: "approved" | "denied",
  approvalId?: string,
): Promise<void> {
  const state = store.get();
  const session = state.activeSession;
  const pending = session?.pendingApproval;
  const id = approvalId ?? pending?.approval_id;
  const runId = session?.runId;
  if (!id || !runId) return;
  const resolved = await safeClientAction(store, () =>
    client.resolveApproval(runId, id, decision, { workspaceId: state.activeWorkspaceId ?? undefined }),
  );
  if (!resolved) return;
  const latest = store.get();
  const latestSession = latest.activeSession;
  const latestPending = latestSession?.pendingApproval;
  store.set({
    ...latest,
    phase: "thinking",
    activeSession: latestSession
      ? { ...latestSession, pendingApproval: latestPending?.approval_id === id ? null : latestPending }
      : latestSession,
  });
}
