import { expect, test } from "bun:test";
import { frame } from "../src/design/borders";
import { spinnerFrame } from "../src/design/spinners";

test("spinner frames stay fixed width", () => {
  const frames = [spinnerFrame("dots", 0), spinnerFrame("dots", 1), spinnerFrame("dots", 2), spinnerFrame("dots", 3)];
  expect(new Set(frames.map((item) => item.length)).size).toBe(1);
});

test("framed panels keep fixed width", () => {
  const rendered = frame("test", "hello", 20).split("\n");
  expect(new Set(rendered.map((line) => line.length)).size).toBe(1);
});
