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

test("candidatesForSlash keeps command context around matches", () => {
  const out = candidatesForSlash("sess");
  expect(out.some((c) => c.label === "/sessions")).toBe(true);
  expect(out.some((c) => c.label === "/diff")).toBe(true);
  expect(candidatesForSlash("zzzz")).toEqual([]);
});

test("candidatesForSlash follows the Paper command order around replay", () => {
  const labels = candidatesForSlash("rep").map((candidate) => candidate.label);
  expect(labels.slice(2, 7)).toEqual(["/diff", "/diff-stat", "/replay", "/sessions", "/skills"]);
});

test("candidatesForFile ranks basename hits ahead of mid-path hits", () => {
  const files = ["docs/TUI.md", "src/main.ts", "tests/main.test.ts"];
  const out = candidatesForFile("main", files);
  expect(out[0]?.label).toBe("src/main.ts");
});

test("candidatesForFile adds real metadata and recent files when available", () => {
  const files = ["src/ui/widgets/Transcript.ts", "tests/ui/transcript.test.ts", "docs/TRANSCRIPT.md", "README.md"];
  const out = candidatesForFile("tra", files, {
    "src/ui/widgets/Transcript.ts": { bytes: 12 * 1024, mtimeMs: 30 },
    "tests/ui/transcript.test.ts": { bytes: 4 * 1024, mtimeMs: 20 },
    "docs/TRANSCRIPT.md": { bytes: 2 * 1024, mtimeMs: 10 },
    "README.md": { bytes: 3 * 1024, mtimeMs: 100 },
  });
  expect(out.map((candidate) => candidate.label)).toEqual([
    "src/ui/widgets/Transcript.ts",
    "tests/ui/transcript.test.ts",
    "docs/TRANSCRIPT.md",
    "— recent —",
    "README.md",
  ]);
  expect(out[0]?.meta).toBe("12kb");
  expect(out[3]?.disabled).toBe(true);
  expect(out[4]?.meta).toBe("3kb");
});

test("candidatesForFile avoids synthetic recent rows without metadata", () => {
  const out = candidatesForFile("tra", ["src/ui/widgets/Transcript.ts", "README.md"]);
  expect(out.map((candidate) => candidate.label)).toEqual(["src/ui/widgets/Transcript.ts"]);
});

test("candidatesForSkill matches case-insensitively", () => {
  const out = candidatesForSkill("READ", [
    { name: "review", path: "skills/review" },
    { name: "reader", path: "skills/reader" },
  ]);
  expect(out.some((c) => c.label === "$reader")).toBe(true);
  expect(out.some((c) => c.label === "$review")).toBe(true);
  expect(candidatesForSkill("zzzz", [{ name: "review", path: "skills/review" }])).toEqual([]);
});

test("candidatesForSkill compacts long prose for picker rows", () => {
  const out = candidatesForSkill("", [
    {
      name: "visual-check",
      path: "skills/visual-check/SKILL.md",
      description: "Capture OpenTUI scenes before calling UI work done",
    },
    {
      name: "paper-review",
      path: "skills/paper-review/SKILL.md",
      description: "Compare the terminal surface against the Paper artboard",
    },
  ]);
  expect(out[0]?.description).toBe("capture TUI scenes");
  expect(out[1]?.description).toBe("compare terminal against Paper");
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
