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
  expect(output).toContain("0001 run.started");
  expect(output).toContain("Events: 3");
});
