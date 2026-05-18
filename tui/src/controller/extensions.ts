import type { TinyAgentClient } from "../backend/client";
import type { Store } from "../state/store";
import { normalizeExtensions } from "../ui/widgets/ExtensionsWidget";
import { appendError } from "./errors";

export async function refreshExtensions(client: TinyAgentClient, store: Store): Promise<void> {
  const workspaceId = store.get().activeWorkspaceId ?? undefined;
  try {
    const raw = await client.listExtensions(workspaceId);
    const extensions = normalizeExtensions(raw);
    store.set({ ...store.get(), extensions });
  } catch (error) {
    appendError(store, error instanceof Error ? error.message : String(error));
  }
}

export async function runExtensionsCommand(client: TinyAgentClient, store: Store): Promise<void> {
  await refreshExtensions(client, store);
  store.set({ ...store.get(), ui: { ...store.get().ui, activePanel: "extensions" } });
}
