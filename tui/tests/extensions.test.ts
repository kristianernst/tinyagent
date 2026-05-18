import { expect, test } from "bun:test";
import { normalizeExtensions } from "../src/ui/widgets/ExtensionsWidget";
import { refreshExtensions } from "../src/controller/extensions";
import type { TinyAgentClient } from "../src/backend/client";
import { emptyState } from "../src/state/reducer";
import { Store } from "../src/state/store";

test("normalizeExtensions maps mcp/lsp/feature kinds", () => {
  const out = normalizeExtensions([
    { name: "mcp", servers: ["s1", "s2"] },
    { name: "lsp", servers: ["pyright"] },
    { name: "todo_memory", enabled: true },
    { name: "future_plugin" },
  ]);
  expect(out[0]?.kind).toBe("mcp");
  expect(out[0]?.servers).toEqual(["s1", "s2"]);
  expect(out[1]?.kind).toBe("lsp");
  expect(out[2]?.kind).toBe("feature");
  expect(out[2]?.enabled).toBe(true);
  expect(out[3]?.kind).toBe("other");
});

test("refreshExtensions populates the store from the backend", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default" });
  const client = {
    listExtensions: async () => [
      { name: "mcp", servers: ["fs"] },
      { name: "lsp", servers: ["ts-server"] },
    ],
  } as unknown as TinyAgentClient;
  await refreshExtensions(client, store);
  expect(store.get().extensions.map((e) => e.name)).toEqual(["mcp", "lsp"]);
  expect(store.get().extensions[0].servers).toEqual(["fs"]);
});

test("refreshExtensions records errors instead of throwing", async () => {
  const store = new Store(emptyState());
  const client = {
    listExtensions: async () => {
      throw new Error("network down");
    },
  } as unknown as TinyAgentClient;
  await refreshExtensions(client, store);
  expect(store.get().errors).toContain("network down");
});
