import { expect, test } from "bun:test";
import { renderReplayCinema } from "../src/components/ReplayCinema";
import { basicRunFixture } from "../src/state/fixtures";

test("replay cinema renders event sequence", () => {
  const output = renderReplayCinema({
    runId: "run_fixture",
    events: basicRunFixture,
    cursorSeq: 1,
    rawEvent: basicRunFixture[0],
    projected: { phase: "thinking", lastSeq: 1, turns: 1, tools: 0, assistantPreview: "" },
    forkDir: "",
    replayMs: 1.2,
  });
  expect(output).toContain("run            fixture");
  expect(output).toContain("saved trace");
  expect(output).toContain("▏ run started");
  expect(output).toContain("trace opened");
  expect(output).toContain("timeline       3 steps");
  expect(output).toContain("cursor 1 · replay 1.2ms");
  expect(output).toContain("turn preview");
  expect(output).toContain("phase          thinking");
  expect(output).toContain("1 turn · 0 tools · 1.2ms replay");
  expect(output).toContain("assistant      response preview");
  expect(output).toContain("selected step");
  expect(output).toContain("step           1");
  expect(output).toContain("task           say hi");
  expect(output).not.toContain("run_fixture");
  expect(output).not.toContain("event detail");
  expect(output).not.toContain("event          0001");
  expect(output).not.toContain("0001");
  expect(output).not.toContain("run.started");
  expect(output).not.toContain("projection");
  expect(output).not.toContain("projected");
  expect(output).not.toContain("event data");
  expect(output).not.toContain('"task"');
  expect(output).not.toContain("Run: run_fixture");
  expect(output).not.toContain("Events: 3");
});

test("replay cinema keeps fork paths out of visible rows", () => {
  const output = renderReplayCinema({
    runId: "run_fixture",
    events: basicRunFixture,
    cursorSeq: 1,
    rawEvent: basicRunFixture[0],
    projected: { phase: "thinking", lastSeq: 1, turns: 1, tools: 0, assistantPreview: "" },
    forkDir: "/private/tmp/tinyagent/fork-0004",
    replayMs: 1.2,
  });
  expect(output).toContain("fork           workspace copy");
  expect(output).toContain("temporary workspace");
  expect(output).not.toContain("fork 0004");
  expect(output).not.toContain("/private/tmp/tinyagent/fork-0004");
});

test("replay cinema uses quiet empty-state copy", () => {
  const output = renderReplayCinema(null);
  expect(output).toContain("replay");
  expect(output).toContain("status         empty");
  expect(output).not.toContain("No replay loaded.");
});
