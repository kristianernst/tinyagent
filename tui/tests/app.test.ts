import { expect, test } from "bun:test";
import { handleCommand, startRunTask } from "../src/app";
import type { TinyAgentClient } from "../src/backend/client";
import { event } from "../src/state/fixtures";
import { createSession, emptyState } from "../src/state/reducer";
import { Store } from "../src/state/store";

test("startRunTask renders on every streamed event", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: createSession("conv") });
  const ticks: number[] = [];
  const client = {
    startRun: async () => ({ run: { run_id: "run_1", run_path: "/repo/.tinyagent/runs/run_1" }, events_url: "/events" }),
    streamEvents: async (_runId: string, onEvent: (item: ReturnType<typeof event>) => void) => {
      onEvent(event(1, "run.started", { task: "live" }));
      onEvent(event(2, "model.text.delta", { delta: "ok" }));
      onEvent(event(3, "run.completed", {}));
    },
  } as unknown as TinyAgentClient;

  const active = await startRunTask(client, store, "live", (seq) => ticks.push(seq));
  await active.done;

  expect(ticks).toEqual([1, 2, 3]);
  expect(store.get().activeSession?.turns[0].assistant).toBe("ok");
  expect(store.get().activeSession?.runPath).toBe("/repo/.tinyagent/runs/run_1");
});

test("streamed events do not write into a switched conversation", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: createSession("conv_original") });
  const ticks: number[] = [];
  const client = {
    startRun: async () => ({ run: { run_id: "run_1", conversation_id: "conv_original" }, events_url: "/events" }),
    streamEvents: async (_runId: string, onEvent: (item: ReturnType<typeof event>) => void) => {
      onEvent({ ...event(1, "run.started", { task: "live" }), conversation_id: "conv_original" });
      store.set({ ...store.get(), activeSession: createSession("conv_other") });
      onEvent({ ...event(2, "model.text.delta", { delta: "late" }), conversation_id: "conv_original" });
    },
  } as unknown as TinyAgentClient;

  const active = await startRunTask(client, store, "live", (seq) => ticks.push(seq));
  await active.done;

  expect(ticks).toEqual([1]);
  expect(store.get().activeSession?.conversationId).toBe("conv_other");
  expect(store.get().activeSession?.turns).toEqual([]);
});

test("interactive approval commands resolve pending approvals", async () => {
  const session = createSession("conv");
  const store = new Store({
    ...emptyState(),
    activeWorkspaceId: "default",
    activeSession: {
      ...session,
      runId: "run_1",
      pendingApproval: {
        approval_id: "approval_1",
        run_id: "run_1",
        turn_id: "turn_1",
        step_id: "step_1",
        action_kind: "shell",
        tool_name: "shell",
        cwd: ".",
        args_preview: "pytest",
        command: "pytest",
        risk: "medium",
      },
    },
  });
  const calls: unknown[] = [];
  const client = {
    resolveApproval: async (...args: unknown[]) => {
      calls.push(args);
      return true;
    },
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "approve", args: [] }, null);

  expect(calls[0]).toEqual(["run_1", "approval_1", "approved", { workspaceId: "default" }]);
  expect(store.get().activeSession?.pendingApproval).toBeNull();
});

test("resume command loads conversation turns into the active session", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: createSession("local") });
  const client = {
    listConversations: async () => [],
    conversationTurns: async () => [
      {
        type: "turn.completed",
        conversation_id: "conv_saved",
        turn_id: "turn_saved",
        run_id: "run_saved",
        status: "completed",
        user_message: { content: "saved prompt" },
        assistant_message: { content_preview: "saved answer" },
      },
    ],
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "resume", args: ["conv_saved"] }, null);

  expect(store.get().activeSession?.conversationId).toBe("conv_saved");
  expect(store.get().activeSession?.turns[0].user).toBe("saved prompt");
  expect(store.get().activeSession?.turns[0].assistant).toBe("saved answer");
});

test("resume without args uses the latest listed session", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: createSession("local") });
  const client = {
    listConversations: async () => [
      {
        conversation_id: "conv_latest",
        title: "latest",
        status: "open",
        active_turn_id: null,
        created_at: "",
        updated_at: "",
        workspace: ".",
        turn_count: 1,
      },
    ],
    conversationTurns: async (conversationId: string) => [
      {
        type: "turn.completed",
        conversation_id: conversationId,
        turn_id: "turn_latest",
        run_id: "run_latest",
        status: "completed",
        user_message: { content: "latest prompt" },
        assistant_message: { content_preview: "latest answer" },
      },
    ],
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "resume", args: [] }, null);

  expect(store.get().activeSession?.conversationId).toBe("conv_latest");
  expect(store.get().activeSession?.turns[0].assistant).toBe("latest answer");
});

test("new command switches away from a resumed conversation identity", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: createSession("conv_saved") });

  await handleCommand({} as TinyAgentClient, store, { id: "new", args: [] }, null);

  expect(store.get().activeSession?.conversationId).not.toBe("conv_saved");
  expect(store.get().activeSession?.turns).toEqual([]);
});

test("new and resume commands are blocked while a run is active", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: createSession("conv_active") });
  const activeRun = {
    runId: "run_active",
    conversationId: "conv_active",
    workspaceId: "default",
    abort: new AbortController(),
    done: Promise.resolve(),
  };

  const afterNew = await handleCommand({} as TinyAgentClient, store, { id: "new", args: [] }, activeRun);
  const afterResume = await handleCommand({} as TinyAgentClient, store, { id: "resume", args: ["conv_other"] }, activeRun);

  expect(afterNew).toBe(activeRun);
  expect(afterResume).toBe(activeRun);
  expect(store.get().activeSession?.conversationId).toBe("conv_active");
  expect(store.get().errors).toContain("Stop the active run before starting a new session.");
  expect(store.get().errors).toContain("Stop the active run before resuming another session.");
});

test("stale stop and approval failures are captured as UI errors", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: { ...createSession("conv"), runId: "run_done" } });
  const client = {
    cancel: async () => {
      throw new Error("Run is not active");
    },
    resolveApproval: async () => {
      throw new Error("Approval not found");
    },
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "stop", args: [] }, null);
  await handleCommand(client, store, { id: "approve", args: ["approval_missing"] }, null);

  expect(store.get().errors).toContain("Run is not active");
  expect(store.get().errors).toContain("Approval not found");
});

test("sessions command renders refreshed session ids in the overlay", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: createSession("local") });
  const client = {
    listConversations: async () => [
      {
        conversation_id: "conv_listed",
        title: "listed session",
        status: "open",
        active_turn_id: null,
        created_at: "",
        updated_at: "",
        workspace: ".",
        turn_count: 1,
      },
    ],
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "sessions", args: [] }, null);

  expect(store.get().ui.activePanel).toBe("sessions");
  expect(store.get().sessions[0].conversation_id).toBe("conv_listed");
});

test("context and diff commands refresh workspace surface data", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: createSession("local") });
  const client = {
    workspaceFiles: async () => ["README.md"],
    gitStatus: async () => ({
      isRepo: true,
      clean: false,
      branch: "main",
      ahead: 0,
      behind: 0,
      files: [{ path: "README.md", status: "modified" }],
      diff: "diff --git a/README.md b/README.md",
      diffTruncated: false,
    }),
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "context", args: [] }, null);

  expect(store.get().workspaceFiles).toEqual(["README.md"]);
  expect(store.get().activeSession?.git?.branch).toBe("main");
  expect(store.get().activeSession?.diff?.paths).toEqual(["README.md"]);
  expect(store.get().ui.activePanel).toBe("context");
});

test("workspace surface refresh clears stale diff when git reports no diff", async () => {
  const store = new Store({
    ...emptyState(),
    activeWorkspaceId: "default",
    activeSession: { ...createSession("local"), diff: { text: "old diff", paths: ["old.txt"], truncated: false } },
  });
  const client = {
    workspaceFiles: async () => ["README.md"],
    gitStatus: async () => ({
      isRepo: true,
      clean: true,
      branch: "main",
      ahead: 0,
      behind: 0,
      files: [],
      diff: "",
      diffTruncated: false,
    }),
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "diff", args: [] }, null);

  expect(store.get().activeSession?.diff?.text).toBe("");
  expect(store.get().activeSession?.diff?.paths).toEqual([]);
});

test("replay rewind and fork commands use real run events", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: { ...createSession("conv"), runId: "run_1" } });
  const calls: unknown[] = [];
  const client = {
    events: async () => [event(1, "run.started", { task: "inspect" }), event(2, "model.text.delta", { delta: "ok" }), event(3, "run.completed", {})],
    forkRun: async (...args: unknown[]) => {
      calls.push(args);
      return { fork_dir: "/tmp/run_1-fork-0002" };
    },
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "replay", args: [] }, null);
  await handleCommand(client, store, { id: "rewind", args: ["2"] }, null);
  await handleCommand(client, store, { id: "fork", args: ["2"] }, null);

  expect(store.get().ui.activePanel).toBe("replay");
  expect(store.get().replay?.cursorSeq).toBe(2);
  expect(store.get().replay?.projected?.assistantPreview).toBe("ok");
  expect(store.get().replay?.forkDir).toContain("fork-0002");
  expect(calls[0]).toEqual(["run_1", "2", "default"]);
});

test("update command checks product update status", async () => {
  const store = new Store(emptyState());
  const client = {
    updateStatus: async () => ({
      current_version: "0.1.0a0",
      channel: "alpha",
      install_kind: "source",
      manifest_source: "",
      checked_at: "",
      latest_version: "",
      available: false,
      reason: "not_checked",
      platform: "darwin-arm64",
      active_version: "",
      previous_version: "",
      artifact: null,
    }),
    checkUpdate: async () => {
      throw new Error("not used");
    },
    applyUpdate: async () => {
      throw new Error("not used");
    },
    rollbackUpdate: async () => {
      throw new Error("not used");
    },
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "update", args: [] }, null);

  expect(store.get().ui.activePanel).toBe("update");
  expect(store.get().updatePanel.result?.channel).toBe("alpha");
  expect(store.get().updatePanel.lastAction).toBe("status");
});

test("review command explains model failures before generic run failure", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: { ...createSession("conv"), runId: "run_1" } });
  const client = {
    events: async () => [
      event(1, "run.started", { task: "fail" }),
      event(2, "model.call.started", { model_call_id: "m1" }),
      event(3, "model.call.failed", { model_call_id: "m1", error: "provider down" }),
      event(4, "run.failed", { reason: "provider down" }),
    ],
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "review", args: [] }, null);

  expect(store.get().ui.activePanel).toBe("review");
  expect(store.get().failure?.source).toBe("model");
  expect(store.get().failure?.failedEvent).toBe("3 model.call.failed");
  expect(store.get().failure?.lastSuccessfulEvent).toBe("2 model.call.started");
});

test("eval command runs suite and renders pass fail state", async () => {
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: createSession("conv") });
  const client = {
    runEvalSuite: async () => ({
      suite_path: "/repo/evals/smoke",
      output_dir: "/repo/.tinyagent/evals/smoke",
      total: 1,
      passed: 1,
      report: "# Tinyagent Eval Report\n\ncases: 1",
      results: [{ case_id: "read-file", success: true, status: "completed" }],
    }),
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "eval", args: ["evals/smoke"] }, null);

  expect(store.get().ui.activePanel).toBe("eval");
  expect(store.get().evalLab.status).toBe("completed");
  expect(store.get().evalLab.results[0].case_id).toBe("read-file");
});

test("skills command lists drafts and can draft from the active run", async () => {
  const draft = {
    draft_id: "draft_run_1",
    name: "run skill",
    path: "/repo/.tinyagent/skill-drafts/draft_run_1",
    status: "draft",
    source_run_id: "run_1",
    created_at: "",
  };
  const store = new Store({ ...emptyState(), activeWorkspaceId: "default", activeSession: { ...createSession("conv"), runId: "run_1" } });
  const client = {
    createSkillDraft: async () => draft,
    listSkillDrafts: async () => [draft],
    showSkillDraft: async () => ({ draft_id: draft.draft_id, markdown: "---\nname: run skill\n---\nUse it." }),
  } as unknown as TinyAgentClient;

  await handleCommand(client, store, { id: "skills", args: ["draft"] }, null);
  await handleCommand(client, store, { id: "skills", args: ["show", "draft_run_1"] }, null);

  expect(store.get().ui.activePanel).toBe("skills");
  expect(store.get().skillForge.drafts[0].draft_id).toBe("draft_run_1");
  expect(store.get().skillForge.markdown).toContain("name: run skill");
});
