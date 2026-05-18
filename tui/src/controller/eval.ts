import type { TinyAgentClient } from "../backend/client";
import type { Store } from "../state/store";
import { appendError } from "./errors";

export async function runEvalCommand(client: TinyAgentClient, store: Store, suitePath?: string): Promise<void> {
  if (!suitePath) {
    appendError(store, "Usage: /eval <suite-path>");
    return;
  }
  const workspaceId = store.get().activeWorkspaceId ?? undefined;
  store.set({
    ...store.get(),
    evalLab: {
      status: "running",
      suitePath,
      outputDir: "",
      report: "",
      results: [],
      error: "",
      command: `tinyagent eval ${suitePath}`,
    },
  });
  try {
    const result = await client.runEvalSuite(suitePath, {
      workspaceId,
      approvalMode: store.get().approvalMode,
      sessionMode: store.get().sessionMode,
    });
    store.set({
      ...store.get(),
      evalLab: {
        status: "completed",
        suitePath: result.suite_path,
        outputDir: result.output_dir,
        report: result.report,
        results: result.results,
        error: "",
        command: `tinyagent eval ${suitePath}`,
      },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    store.set({ ...store.get(), evalLab: { ...store.get().evalLab, status: "failed", error: message } });
    appendError(store, message);
  }
}
