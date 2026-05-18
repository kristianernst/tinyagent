import type { TinyAgentClient } from "../backend/client";
import type { Store } from "../state/store";
import { appendError } from "./errors";

export async function runUpdateCommand(
  client: TinyAgentClient,
  store: Store,
  args: string[],
  hasActiveRun: boolean,
): Promise<void> {
  const action = args[0] ?? "status";
  const manifestSource = args[1];
  const channel = "alpha";
  try {
    if (action === "check") {
      store.set({ ...store.get(), updatePanel: { ...store.get().updatePanel, status: "checking", error: "" } });
      const result = await client.checkUpdate({ channel, manifestSource });
      store.set({ ...store.get(), updatePanel: { status: "ready", result, lastAction: "check", error: "" } });
      return;
    }
    if (action === "apply") {
      if (hasActiveRun) {
        appendError(store, "Stop the active run before applying an update.");
        return;
      }
      store.set({ ...store.get(), updatePanel: { ...store.get().updatePanel, status: "applying", error: "" } });
      const result = await client.applyUpdate({ channel, manifestSource });
      store.set({ ...store.get(), updatePanel: { status: "ready", result, lastAction: "apply", error: "" } });
      return;
    }
    if (action === "rollback") {
      if (hasActiveRun) {
        appendError(store, "Stop the active run before rolling back.");
        return;
      }
      const result = await client.rollbackUpdate();
      store.set({ ...store.get(), updatePanel: { status: "ready", result, lastAction: "rollback", error: "" } });
      return;
    }
    const result = await client.updateStatus();
    store.set({ ...store.get(), updatePanel: { status: "ready", result, lastAction: "status", error: "" } });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ ...store.get(), updatePanel: { ...store.get().updatePanel, status: "failed", error: message } });
    appendError(store, message);
  }
}
