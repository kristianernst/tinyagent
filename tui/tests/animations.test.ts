import { expect, test } from "bun:test";
import { createAnimator } from "../src/ui/animations";

test("createAnimator returns a noop animator when @opentui/core is absent", () => {
  const a = createAnimator(null);
  expect(typeof a.fadeIn).toBe("function");
  expect(a.fadeIn({}).cancel).toBeDefined();
  a.cancelAll();
});

test("animator uses opentui.createTimeline when present", () => {
  const calls: string[] = [];
  const fakeTl = { add: () => fakeTl, play: () => calls.push("play"), pause: () => calls.push("pause") };
  const fakeOpentui = { createTimeline: () => fakeTl };
  const a = createAnimator(fakeOpentui as any);
  const node = { opacity: 0 };
  const handle = a.fadeIn(node, { duration: 100 });
  expect(calls).toContain("play");
  handle.cancel();
  expect(calls).toContain("pause");
});

test("fadeIn writes the target opacity directly when timeline creation throws", () => {
  const fakeOpentui = {
    createTimeline: () => {
      throw new Error("nope");
    },
  };
  const a = createAnimator(fakeOpentui as any);
  const node = { opacity: 0 };
  a.fadeIn(node, { to: 0.9 });
  expect(node.opacity).toBe(0.9);
});
