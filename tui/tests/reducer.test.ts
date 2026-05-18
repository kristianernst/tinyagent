import { expect, test } from "bun:test";
import { applyLocalCommand } from "../src/commands";
import { renderRootShell } from "../src/components/RootShell";
import { replayForPerf, truncateDiff } from "../src/perf";
import { schemaVersion } from "../src/protocol/schema";
import { createSession, emptyState, reduceEvent, replayEvents } from "../src/state/reducer";
import { basicRunFixture, event } from "../src/state/fixtures";

test("reducer projects streamed assistant output", () => {
  const state = replayEvents(emptyState(), basicRunFixture);
  const turn = state.activeSession?.turns[0];

  expect(turn?.user).toBe("say hi");
  expect(turn?.assistant).toBe("hi");
  expect(turn?.phase).toBe("done");
  expect(state.activeSession?.lastSeq).toBe(3);
});

test("reducer tracks tools, approvals, artifacts, diffs, and usage", () => {
  let state = emptyState();
  state = reduceEvent(state, event(1, "run.started", { task: "full" }));
  state = reduceEvent(state, event(2, "model.reasoning.delta", { model_call_id: "m1", delta: "think" }));
  state = reduceEvent(state, event(3, "model.tool_call.assembly.completed", { tool_call_id: "c1", tool: "shell", args: { cmd: "pytest" } }));
  state = reduceEvent(state, event(4, "tool.execution.output.delta", { tool_call_id: "c1", delta: "pass" }));
  state = reduceEvent(state, event(5, "tool.execution.completed", { tool_call_id: "c1", tool: "shell" }));
  state = reduceEvent(state, event(6, "approval.requested", { approval_id: "a1", tool_name: "shell", risk: "medium", command: "pytest" }));
  state = reduceEvent(state, event(7, "approval.resolved", { approval_id: "a1" }));
  state = reduceEvent(state, event(8, "artifact.created", { path: "final.md", kind: "run_output", bytes: 12 }));
  state = reduceEvent(state, event(9, "patch.applied", { paths: ["README.md"], output: "diff --git" }));
  state = reduceEvent(state, event(10, "model.usage", { input_tokens: 10, output_tokens: 5, total_tokens: 15, latency_ms: 42 }));

  const turn = state.activeSession?.turns[0];
  expect(turn?.reasoning[0].text).toBe("think");
  expect(turn?.tools[0].status).toBe("done");
  expect(turn?.tools[0].output).toBe("pass");
  expect(state.activeSession?.pendingApproval).toBeNull();
  expect(state.activeSession?.artifacts[0].path).toBe("final.md");
  expect(state.activeSession?.diff?.paths).toEqual(["README.md"]);
  expect(state.activeSession?.usage.totalTokens).toBe(15);
});

test("commands switch real local TUI modes", () => {
  let state = emptyState();
  state = applyLocalCommand(state, "plan");
  expect(state.sessionMode).toBe("plan");
  state = applyLocalCommand(state, "build");
  expect(state.sessionMode).toBe("normal");
  state = applyLocalCommand(state, "always-approve");
  expect(state.approvalMode).toBe("yolo");
  state = applyLocalCommand(state, "theme");
  expect(state.ui.activePanel).toBe("theme");
  expect(state.ui.theme).toBe("tiny-light");
});

test("schema export is available to the TUI", () => {
  expect(schemaVersion()).toBe(1);
});

test("10k fixture event replay preserves state", async () => {
  const fixture = await Bun.file(new URL("../fixtures/fake-run-long.jsonl", import.meta.url)).text();
  const events = fixture
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line));
  const perf = replayForPerf(events);
  expect(perf.eventCount).toBe(10_000);
  expect(perf.lastSeq).toBe(10_000);
});

test("large diffs are intentionally truncated", () => {
  const diff = "x".repeat(200_100);
  const truncated = truncateDiff(diff);
  expect(truncated.truncated).toBe(true);
  expect(truncated.text).toContain("diff truncated");
});

test("sessions panel renders refreshed session ids", () => {
  const state = {
    ...emptyState(),
    sessions: [
      {
        conversation_id: "conv_visible",
        title: "visible session",
        status: "open",
        active_turn_id: null,
        created_at: "",
        updated_at: "",
        workspace: ".",
        turn_count: 1,
      },
    ],
    ui: { ...emptyState().ui, activePanel: "sessions" },
  };

  expect(renderRootShell(state)).toContain("conv_visible");
});

test("root shell renders command errors", () => {
  const state = { ...emptyState(), errors: ["Run is not active"] };

  expect(renderRootShell(state)).toContain("Run is not active");
});

test("root shell renders context usage model and diff panels", () => {
  const base = {
    ...emptyState(),
    workspaces: [{ workspace_id: "default", name: "Repo", root: "/repo" }],
    activeWorkspaceId: "default",
    workspaceFiles: ["README.md"],
    activeSession: {
      ...createSession("conv"),
      runId: "run_active",
      runPath: "/repo/.tinyagent/runs/run_active",
      git: { isRepo: true, clean: false, branch: "main", ahead: 0, behind: 0, files: [{ path: "README.md", status: "modified" }], diff: "diff --git", diffTruncated: false },
      diff: { text: "diff --git", paths: ["README.md"], truncated: false },
      usage: { inputTokens: 1, outputTokens: 2, totalTokens: 3, modelCalls: 1, latencyMs: 4 },
    },
    provider: "fake",
    model: "test-model",
  };

  expect(renderRootShell({ ...base, ui: { ...base.ui, activePanel: "context" } })).toContain("Files: 1");
  expect(renderRootShell({ ...base, ui: { ...base.ui, activePanel: "usage" } })).toContain("Total tokens: 3");
  expect(renderRootShell({ ...base, ui: { ...base.ui, activePanel: "model" } })).toContain("Provider: fake");
  expect(renderRootShell({ ...base, ui: { ...base.ui, activePanel: "diff" } })).toContain("diff --git");
  expect(renderRootShell({ ...base, ui: { ...base.ui, activePanel: "headless" } })).toContain("tinyagent run");
  expect(renderRootShell({ ...base, ui: { ...base.ui, activePanel: "headless" } })).toContain("/repo/.tinyagent/runs/run_active");
  expect(renderRootShell({ ...base, ui: { ...base.ui, activePanel: "headless" } })).toContain("jq .usage");
  expect(renderRootShell({ ...base, ui: { ...base.ui, activePanel: "acp" } })).toContain("tinyagent agent stdio --protocol acp");
  expect(renderRootShell({ ...base, ui: { ...base.ui, activePanel: "update" } })).toContain("Update channel: alpha");
  expect(renderRootShell({ ...base, ui: { ...base.ui, activePanel: "transcript" } })).toContain("Use /diff to inspect");
});
