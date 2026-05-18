import { expect, test } from "bun:test";
import type { TinyAgentClient } from "../src/backend/client";
import { handleCommand } from "../src/controller/commands";
import { startRunTask } from "../src/controller/runs";
import { event } from "../src/state/fixtures";
import { createSession, emptyState } from "../src/state/reducer";
import { Store } from "../src/state/store";

test("controller exports parity: handleCommand toggles reasoning UI", async () => {
  const store = new Store({ ...emptyState(), activeSession: createSession("local") });
  await handleCommand({} as TinyAgentClient, store, { id: "reason", args: [] }, null);
  expect(store.get().ui.showReasoning).toBe(true);
  await handleCommand({} as TinyAgentClient, store, { id: "reason", args: [] }, null);
  expect(store.get().ui.showReasoning).toBe(false);
});

test("controller exports parity: handleCommand toggles rail visibility", async () => {
  const store = new Store(emptyState());
  await handleCommand({} as TinyAgentClient, store, { id: "rail", args: [] }, null);
  expect(store.get().ui.rightRail).toBe(false);
  await handleCommand({} as TinyAgentClient, store, { id: "rail", args: [] }, null);
  expect(store.get().ui.rightRail).toBe(true);
});

test("controller exports parity: startRunTask streams to the store", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: createSession("conv") });
  const client = {
    startRun: async () => ({ run: { run_id: "run_x", conversation_id: "conv" }, events_url: "/x" }),
    streamEvents: async (_runId: string, onEvent: (e: ReturnType<typeof event>) => void) => {
      onEvent(event(1, "run.started", { task: "hi" }));
      onEvent(event(2, "model.text.delta", { delta: "hi" }));
      onEvent(event(3, "run.completed", {}));
    },
  } as unknown as TinyAgentClient;
  const active = await startRunTask(client, store, "hi");
  await active.done;
  expect(store.get().activeSession?.turns[0].assistant).toBe("hi");
});
