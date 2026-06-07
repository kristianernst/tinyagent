import { expect, test } from "bun:test";
import { applyLocalCommand } from "../src/commands";
import { renderCommandPalette } from "../src/components/CommandPalette";
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
  state = reduceEvent(state, event(3, "model.reasoning.completed", { model_call_id: "m1", reason: "think" }));
  state = reduceEvent(state, event(4, "model.tool_call.assembly.completed", { tool_call_id: "c1", tool: "shell", args: { cmd: "pytest" } }));
  state = reduceEvent(state, event(5, "tool.execution.output.delta", { tool_call_id: "c1", delta: "pass" }));
  state = reduceEvent(state, event(6, "tool.execution.completed", { tool_call_id: "c1", tool: "shell" }));
  state = reduceEvent(state, event(7, "approval.requested", { approval_id: "a1", tool_name: "shell", risk: "medium", command: "pytest" }));
  state = reduceEvent(state, event(8, "approval.resolved", { approval_id: "a1" }));
  state = reduceEvent(state, event(9, "artifact.created", { path: "final.md", kind: "run_output", bytes: 12 }));
  state = reduceEvent(state, event(10, "patch.applied", { paths: ["README.md"], output: "diff --git" }));
  state = reduceEvent(state, event(11, "model.usage", { input_tokens: 10, output_tokens: 5, total_tokens: 15, latency_ms: 42 }));

  const turn = state.activeSession?.turns[0];
  expect(turn?.reasoning[0].text).toBe("think");
  expect(turn?.reasoning[0].startedAt).toBe("2026-05-17T00:00:02Z");
  expect(turn?.reasoning[0].completedAt).toBe("2026-05-17T00:00:03Z");
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
  expect(state.ui.theme).toBe("paper-light");
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

test("sessions panel renders refreshed sessions without raw ids", () => {
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

  const shell = renderRootShell(state);
  expect(shell).toContain("◆ tinyagent");
  expect(shell).toContain("┆ sessions");
  expect(shell).toContain("visible session");
  expect(shell).toContain("open");
  expect(shell).toContain("1 turn");
  expect(shell).not.toContain("conv_visible");
  expect(shell).not.toContain("╭ transcript ");
  expect(shell).not.toContain("╭ rail ");
});

test("root shell renders command errors", () => {
  const state = { ...emptyState(), errors: ["Run is not active"] };

  const shell = renderRootShell(state);
  expect(shell).toContain("Run is not active");
  expect(shell).not.toContain("0 tok");
  expect(shell).not.toContain("no-workspace");
});

test("root shell fallback chrome uses Paper context meter grammar", () => {
  const base = {
    ...emptyState(),
    model: "gpt-5",
    workspaces: [{ workspace_id: "default", name: "Repo", root: "/repo" }],
    activeWorkspaceId: "default",
    activeSession: {
      ...createSession("conv"),
      usage: { inputTokens: 1, outputTokens: 2, totalTokens: 3, modelCalls: 1, latencyMs: 4 },
    },
  };

  const quiet = renderRootShell(base);
  expect(quiet).toContain("◆ tinyagent │ ws : Repo │ model : gpt-5");
  expect(quiet).toContain("⦗ idle ⦘");
  expect(quiet).toContain("ctx ▱▱▱▱▱  0%");
  expect(quiet).not.toContain("ctx 0%");
  expect(quiet).not.toContain("— brand");

  const warning = renderRootShell({
    ...base,
    activeSession: {
      ...base.activeSession,
      usage: { inputTokens: 104_000, outputTokens: 1_000, totalTokens: 105_000, modelCalls: 4, latencyMs: 1200 },
    },
  });
  expect(warning).toContain("ctx ▰▰▰▰▱ 82% — warning");
  expect(warning).not.toContain("⦗ compact ⦘");

  const danger = renderRootShell({
    ...base,
    activeSession: {
      ...base.activeSession,
      usage: { inputTokens: 122_000, outputTokens: 1_000, totalTokens: 123_000, modelCalls: 4, latencyMs: 1200 },
    },
  });
  expect(danger).toContain("⦗ compact ⦘");
  expect(danger).toContain("ctx ▰▰▰▰▰ 96% — danger");
});

test("root shell fallback approval uses Paper decision copy", () => {
  const shell = renderRootShell({
    ...emptyState(),
    activeSession: {
      ...createSession("conv"),
      pendingApproval: {
        approval_id: "approval_copy",
        tool_name: "shell",
        action_kind: "run-command",
        risk: "high",
        command: "rm -rf node_modules",
        args_preview: "rm -rf node_modules",
        cwd: "/Users/kristian/work/dev/tinyagent",
        turn_id: "turn 7",
      } as any,
    },
  });

  expect(shell).toContain("⦗ approve ⦘ shell");
  expect(shell).toContain("command     rm -rf node_modules");
  expect(shell).toContain("in          /Users/kristian/work/dev/tinyagent");
  expect(shell).toContain("requested by: agent · turn 7");
  expect(shell).toContain("risk: high · review first");
  expect(shell).toContain("⌜y⌟ allow once");
  expect(shell).toContain("⌜a⌟ allow for session");
  expect(shell).toContain("⌜n⌟ deny");
  expect(shell).toContain("⌜e⌟ edit command");
  expect(shell).toContain("esc dismisses");
  expect(shell).not.toContain("/approve");
  expect(shell).not.toContain("/deny");
  expect(shell).not.toContain("choose once");
  expect(shell).not.toContain("review before allowing");
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

  const context = renderRootShell({ ...base, ui: { ...base.ui, activePanel: "context" } });
  expect(context).toContain("files         1");
  expect(context).toContain("file mentions");
  expect(context).not.toContain("workspace mention index");
  expect(context).not.toContain("Files:");

  const usage = renderRootShell({ ...base, ui: { ...base.ui, activePanel: "usage" } });
  expect(usage).toContain("total tokens  3");
  expect(usage).not.toContain("Total tokens:");

  const model = renderRootShell({ ...base, ui: { ...base.ui, activePanel: "model" } });
  expect(model).toContain("provider      fake");
  expect(model).not.toContain("Provider:");

  const diff = renderRootShell({ ...base, ui: { ...base.ui, activePanel: "diff" } });
  expect(diff).toContain("diff --git");
  expect(diff).toContain("files         README.md");
  expect(diff).not.toContain("Files:");

  const headless = renderRootShell({ ...base, ui: { ...base.ui, activePanel: "headless" } });
  expect(headless).toContain("tinyagent run");
  expect(headless).toContain('tinyagent run "<prompt>" --stream text');
  expect(headless).toContain("tinyagent replay <run-id>");
  expect(headless).toContain("tinyagent fork <run-path> --at 1");
  expect(headless).toContain("fork          from step 1");
  expect(headless).toContain("replay        review run");
  expect(headless).not.toContain("project run");
  expect(headless).not.toContain("tinyagent replay run_active");
  expect(headless).not.toContain("from event");
  expect(headless).not.toContain("/repo/.tinyagent/runs/run_active");
  expect(headless).not.toContain("--output-format");
  expect(headless).not.toContain("jsonl");
  expect(headless).not.toContain("--debug");
  expect(headless).not.toContain("jq .usage");
  expect(headless).toContain("saved with run summary");
  expect(headless).toContain("draft skill   capture pattern");
  expect(headless).toContain("usage         3 tok · 1 call");
  expect(headless).toContain("bridge        connect clients");
  expect(headless).not.toContain("stdio         protocol bridge");
  expect(headless).not.toContain("from run");
  expect(headless).not.toContain("3 tokens");
  expect(headless).toContain("same trace · cli parity");
  expect(headless).not.toContain("run json");
  expect(headless).not.toContain("usage json");
  expect(headless).not.toContain("Current usage:");
  const acp = renderRootShell({ ...base, ui: { ...base.ui, activePanel: "acp" } });
  expect(acp).toContain("tinyagent agent stdio --protocol acp");
  expect(acp).not.toContain("Transport:");

  const update = renderRootShell({
    ...base,
    updatePanel: {
      status: "ready",
      lastAction: "check",
      error: "",
      result: {
        current_version: "0.4.1",
        channel: "alpha",
        install_kind: "uv-tool",
        manifest_source: "https://updates.tinyagent.dev/alpha.json",
        checked_at: "2026-05-25T18:40:00Z",
        latest_version: "0.4.2",
        available: true,
        reason: "new alpha build available",
        platform: "darwin-arm64",
        active_version: "0.4.1",
        previous_version: "0.4.0",
        artifact: null,
      },
    },
    ui: { ...base.ui, activePanel: "update" },
  });
  expect(update).toContain("channel       alpha");
  expect(update).toContain("source        alpha feed");
  expect(update).toContain("checked release service");
  expect(update).toContain("⦗ update 0.4.2 ⦘");
  expect(update).not.toContain("manifest      alpha remote");
  expect(update).not.toContain("updates.tinyagent.dev/alpha.json");
  expect(update).not.toContain("https://updates.tinyagent.dev/alpha.json");
  expect(update).not.toContain("Update channel:");

  const theme = renderRootShell({ ...base, ui: { ...base.ui, activePanel: "theme" } });
  expect(theme).toContain("palette       paper-dark");
  expect(theme).not.toContain("Theme:");
  const activity = renderRootShell({ ...base, sessionMode: "plan", ui: { ...base.ui, activePanel: "activity" } });
  expect(activity).toContain("┆ activity");
  expect(activity).toContain("session mode");
  expect(activity).toContain("mode          plan");
  expect(activity).toContain("write tools locked");
  expect(activity).not.toContain("Plan mode active");
  expect(activity).not.toContain("/build exits plan");
  const help = renderRootShell({ ...base, ui: { ...base.ui, activePanel: "help" } });
  expect(help).toContain("⦗ / ⦘ commands");
  expect(help).toContain("/new");
  expect(help).toContain("start new session");
  for (const hidden of ["/always-approve", "/approve", "/deny", "/compact-mode", "/rewind", "/fork"]) {
    expect(help).not.toContain(hidden);
  }
  expect(help).toContain("⌜↑↓⌟ move");
  expect(help).toContain("⌜↑↓⌟ move   ⌜⏎⌟ run   ⌜esc⌟ cancel");
  expect(help).not.toContain("⌜↑↓⌟ move · ⌜⏎⌟ run · ⌜esc⌟ cancel");
  expect(help).toContain("⌜esc⌟ cancel");
  expect(help).not.toContain("⌜esc⌟ collapse");
  const noMatchHelp = renderCommandPalette("nope-no-command");
  expect(noMatchHelp).toContain("no matches · ⌜esc⌟ cancel");
  expect(noMatchHelp).not.toContain("no matches · ⌜esc⌟ collapse");
  const hiddenCompatibilityCommand = renderCommandPalette("approve");
  expect(hiddenCompatibilityCommand).toContain("no matches · ⌜esc⌟ cancel");
  expect(hiddenCompatibilityCommand).not.toContain("/approve");
  const visiblePaperCommand = renderCommandPalette("usage");
  expect(visiblePaperCommand).toContain("/usage");
  expect(visiblePaperCommand).toContain("show token usage");
  const filteredHelpCommand = renderCommandPalette("help");
  expect(filteredHelpCommand).toContain("/help");
  expect(filteredHelpCommand).toContain("show commands");
  const transcript = renderRootShell({ ...base, ui: { ...base.ui, activePanel: "transcript" } });
  expect(transcript).toContain("inspect /diff");
  expect(transcript).not.toContain("Use /diff to inspect");
});
