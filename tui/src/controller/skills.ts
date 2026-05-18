import type { TinyAgentClient } from "../backend/client";
import type { Store } from "../state/store";
import { appendError } from "./errors";

export async function runSkillsCommand(client: TinyAgentClient, store: Store, args: string[]): Promise<void> {
  const workspaceId = store.get().activeWorkspaceId ?? undefined;
  const action = args[0] ?? "list";
  store.set({ ...store.get(), skillForge: { ...store.get().skillForge, status: "loading", error: "" } });
  try {
    if (action === "draft") {
      const runId = args[1] ?? store.get().activeSession?.runId ?? "";
      if (!runId) throw new Error("Usage: /skills draft <run-id>");
      const draft = await client.createSkillDraft(runId, workspaceId);
      const drafts = await client.listSkillDrafts(workspaceId);
      store.set({
        ...store.get(),
        skillForge: { status: "ready", drafts, selectedDraftId: draft.draft_id, markdown: "", lastAction: `drafted ${draft.draft_id}`, error: "" },
      });
      return;
    }
    if (action === "show") {
      const draftId = args[1] ?? store.get().skillForge.selectedDraftId;
      if (!draftId) throw new Error("Usage: /skills show <draft-id>");
      const shown = await client.showSkillDraft(draftId, workspaceId);
      store.set({
        ...store.get(),
        skillForge: { ...store.get().skillForge, status: "ready", selectedDraftId: draftId, markdown: shown.markdown, lastAction: `show ${draftId}`, error: "" },
      });
      return;
    }
    if (action === "install" || action === "reject") {
      const draftId = args[1] ?? store.get().skillForge.selectedDraftId;
      if (!draftId) throw new Error(`Usage: /skills ${action} <draft-id>`);
      const result = action === "install" ? await client.installSkillDraft(draftId, workspaceId) : await client.rejectSkillDraft(draftId, workspaceId);
      const drafts = await client.listSkillDrafts(workspaceId);
      store.set({
        ...store.get(),
        skillForge: { status: "ready", drafts, selectedDraftId: draftId, markdown: "", lastAction: `${action} ${result.path}`, error: "" },
      });
      return;
    }
    const drafts = await client.listSkillDrafts(workspaceId);
    store.set({ ...store.get(), skillForge: { ...store.get().skillForge, status: "ready", drafts, lastAction: "list", error: "" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ ...store.get(), skillForge: { ...store.get().skillForge, status: "failed", error: message } });
    appendError(store, message);
  }
}
