import { expect, test } from "bun:test";
import {
  applyCandidate,
  candidatesForFile,
  candidatesForSkill,
  candidatesForSlash,
  detectMention,
  pickCandidates,
} from "../src/ui/mentions";

test("detectMention finds a slash trigger at the start of input", () => {
  const detection = detectMention("/sess");
  expect(detection?.trigger).toBe("/");
  expect(detection?.query).toBe("sess");
  expect(detection?.start).toBe(0);
});

test("detectMention finds @file mention with cursor inside the token", () => {
  // Cursor right after "app" — before the trailing whitespace.
  const detection = detectMention("look at @src/app cwd", 16);
  expect(detection?.trigger).toBe("@");
  expect(detection?.query).toBe("src/app");
});

test("detectMention finds $skill mention after newline", () => {
  const detection = detectMention("review\n$test", 13);
  expect(detection?.trigger).toBe("$");
  expect(detection?.query).toBe("test");
});

test("detectMention ignores triggers inside tokens (email, path, etc.)", () => {
  expect(detectMention("user@example.com")).toBeNull();
  expect(detectMention("path/to/file")).toBeNull();
  // "spend $50" with cursor right after "50" — `$` is preceded by whitespace, so it matches.
  expect(detectMention("spend $50", 9)?.trigger).toBe("$");
});

test("detectMention returns null when cursor sits past a whitespace", () => {
  // typed "/sess " — cursor after the space.
  const detection = detectMention("/sess ", 6);
  expect(detection).toBeNull();
});

test("candidatesForSlash filters known commands", () => {
  const out = candidatesForSlash("sess");
  expect(out.some((c) => c.label === "/sessions")).toBe(true);
  expect(out.length).toBeGreaterThan(0);
});

test("candidatesForFile ranks basename hits ahead of mid-path hits", () => {
  const files = ["docs/TUI.md", "src/main.ts", "tests/main.test.ts"];
  const out = candidatesForFile("main", files);
  expect(out[0]?.label).toBe("src/main.ts");
});

test("candidatesForSkill matches case-insensitively", () => {
  const out = candidatesForSkill("READ", [
    { name: "review", path: "skills/review" },
    { name: "reader", path: "skills/reader" },
  ]);
  expect(out.length).toBe(1);
  expect(out[0]?.label).toBe("$reader");
});

test("pickCandidates dispatches by trigger", () => {
  const slash = pickCandidates({ trigger: "/", query: "sess", start: 0, end: 5 }, [], []);
  expect(slash[0]?.label.startsWith("/")).toBe(true);
  const file = pickCandidates({ trigger: "@", query: "main", start: 0, end: 5 }, ["src/main.ts"], []);
  expect(file[0]?.label).toBe("src/main.ts");
  const skill = pickCandidates({ trigger: "$", query: "rev", start: 0, end: 4 }, [], [{ name: "review", path: "skills/review" }]);
  expect(skill[0]?.label).toBe("$review");
});

test("applyCandidate splices the chosen insert text into the prompt", () => {
  const text = "look at @src/ma";
  const detection = detectMention(text)!;
  const updated = applyCandidate(text, detection, { label: "src/main.ts", insert: "@src/main.ts " });
  expect(updated).toBe("look at @src/main.ts ");
});
