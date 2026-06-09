import { expect, test } from "bun:test";
import { frame } from "../src/design/borders";
import { FRAME_MS, motion, motionMs } from "../src/design/primitives";
import { spinnerBeatFrame, spinnerFrame } from "../src/design/spinners";

test("spinner frames stay fixed width", () => {
  const frames = [spinnerFrame("dots", 0), spinnerFrame("dots", 1), spinnerFrame("dots", 2), spinnerFrame("dots", 3)];
  expect(new Set(frames.map((item) => item.length)).size).toBe(1);
});

test("live spinner advances on the Paper beat cadence", () => {
  expect(spinnerBeatFrame("braille", 0)).toBe("⠋");
  expect(spinnerBeatFrame("braille", 1)).toBe("⠙");
  expect(spinnerBeatFrame("braille", 4)).toBe("⠙");
  expect(spinnerBeatFrame("braille", 5)).toBe("⠹");
});

test("motion millisecond values mirror the Paper frame labels", () => {
  expect(FRAME_MS).toBe(33);
  expect(motion.fast).toBe(2);
  expect(motion.beat).toBe(4);
  expect(motion.slow).toBe(8);
  expect(motion.dwell).toBe(16);
  expect(motion.streamGate).toBe(1);
  expect(motionMs.fast).toBe(66);
  expect(motionMs.beat).toBe(132);
  expect(motionMs.slow).toBe(266);
  expect(motionMs.dwell).toBe(533);
  expect(motionMs.streamGate).toBe(33);
});

test("framed panels keep fixed width", () => {
  const rendered = frame("test", "hello", 20).split("\n");
  expect(new Set(rendered.map((line) => line.length)).size).toBe(1);
});
