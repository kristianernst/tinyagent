import { expect, test } from "bun:test";
import { FocusStack } from "../src/ui/focus";

function make(id: string, log: string[]) {
  return {
    id,
    focus: () => log.push(`focus:${id}`),
    blur: () => log.push(`blur:${id}`),
  };
}

test("registerCycle focuses the first member", () => {
  const log: string[] = [];
  const focus = new FocusStack();
  focus.registerCycle([make("composer", log), make("transcript", log), make("rail", log)]);
  expect(log).toEqual(["focus:composer"]);
});

test("cycleNext blurs current and focuses next, with wraparound", () => {
  const log: string[] = [];
  const focus = new FocusStack();
  focus.registerCycle([make("composer", log), make("transcript", log)]);
  log.length = 0;
  focus.cycleNext();
  focus.cycleNext();
  expect(log).toEqual(["blur:composer", "focus:transcript", "blur:transcript", "focus:composer"]);
});

test("push focuses overlay and pop restores prior", () => {
  const log: string[] = [];
  const focus = new FocusStack();
  const composer = make("composer", log);
  focus.registerCycle([composer]);
  log.length = 0;
  const modal = make("modal", log);
  focus.push(modal);
  expect(log).toEqual(["focus:modal"]);
  focus.pop();
  expect(log[log.length - 1]).toBe("focus:composer");
});
