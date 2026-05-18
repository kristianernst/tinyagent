import { expect, test } from "bun:test";
import { commands, parseCommand } from "../src/commands";
import { keymap } from "../src/keymap";

test("command parser recognizes product commands", () => {
  expect(parseCommand("/plan")).toBe("plan");
  expect(parseCommand("/usage now")).toBe("usage");
  expect(parseCommand("plain text")).toBeNull();
});

test("command palette exposes only wired commands", () => {
  const ids = commands.map((command) => command.id);
  expect(ids).toContain("eval");
  expect(ids).toContain("skills");
  expect(ids).toContain("update");
  expect(ids).toContain("replay");
  expect(ids).toContain("fork");
  expect(ids).toContain("headless");
  expect(ids).toContain("acp");
  expect(parseCommand("/eval")).toBe("eval");
  expect(parseCommand("/update")).toBe("update");
  expect(parseCommand("/headless")).toBe("headless");
});

test("terminal keymap exposes core controls", () => {
  expect(keymap["Ctrl+C"]).toBe("interrupt");
  expect(keymap["Ctrl+K"]).toBe("palette");
  expect(keymap["Ctrl+D"]).toBe("diff");
});
