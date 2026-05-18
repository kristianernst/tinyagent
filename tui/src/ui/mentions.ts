import { commands } from "../commands";
import type { ExtensionEntry, MentionTrigger, SkillEntry } from "../state/reducer";

export type MentionDetection = {
  trigger: MentionTrigger;
  query: string;
  start: number;
  end: number;
};

export type MentionCandidate = {
  label: string;
  description?: string;
  insert: string;
};

const TRIGGERS: MentionTrigger[] = ["/", "@", "$"];

/**
 * Find an active mention (one of `/`, `@`, `$`) in the composer text,
 * positioned at or before the cursor. Returns null if the cursor is
 * not within a mention.
 */
export function detectMention(text: string, cursor: number = text.length): MentionDetection | null {
  if (!text) return null;
  const pos = Math.max(0, Math.min(text.length, cursor));
  for (let i = pos - 1; i >= 0; i -= 1) {
    const ch = text[i];
    if (ch === " " || ch === "\n" || ch === "\t") return null;
    if (ch === "/" || ch === "@" || ch === "$") {
      const before = i === 0 ? "" : text[i - 1];
      // Treat as a mention only when the trigger is at start-of-input or
      // preceded by whitespace. Mid-token occurrences (e.g. `/` inside a
      // path, `@` inside an email) are skipped — keep walking earlier so
      // paths like "@src/main" still resolve to the `@` mention.
      if (!before || before === " " || before === "\n" || before === "\t") {
        return {
          trigger: ch as MentionTrigger,
          query: text.slice(i + 1, pos),
          start: i,
          end: pos,
        };
      }
    }
  }
  return null;
}

export function candidatesForSlash(query: string): MentionCandidate[] {
  const needle = query.toLowerCase();
  return commands
    .filter((command) => !needle || command.id.includes(needle) || command.title.toLowerCase().includes(needle))
    .slice(0, 8)
    .map((command) => ({
      label: `/${command.id}`,
      description: command.title,
      insert: `/${command.id} `,
    }));
}

export function candidatesForFile(query: string, files: string[]): MentionCandidate[] {
  const needle = query.toLowerCase();
  const ranked = files
    .map((path) => ({ path, score: rankFile(path, needle) }))
    .filter((row) => row.score >= 0)
    .sort((a, b) => a.score - b.score)
    .slice(0, 12);
  return ranked.map(({ path }) => ({
    label: path,
    description: "",
    insert: `@${path} `,
  }));
}

export function candidatesForSkill(query: string, skills: SkillEntry[]): MentionCandidate[] {
  const needle = query.toLowerCase();
  return skills
    .filter((skill) => !needle || skill.name.toLowerCase().includes(needle))
    .slice(0, 10)
    .map((skill) => ({
      label: `$${skill.name}`,
      description: skill.description ?? skill.path,
      insert: `$${skill.name} `,
    }));
}

export function pickCandidates(
  detection: MentionDetection,
  files: string[],
  skills: SkillEntry[],
): MentionCandidate[] {
  switch (detection.trigger) {
    case "/":
      return candidatesForSlash(detection.query);
    case "@":
      return candidatesForFile(detection.query, files);
    case "$":
      return candidatesForSkill(detection.query, skills);
  }
}

export function applyCandidate(text: string, detection: MentionDetection, candidate: MentionCandidate): string {
  return `${text.slice(0, detection.start)}${candidate.insert}${text.slice(detection.end)}`;
}

export function isMentionTrigger(ch: string): ch is MentionTrigger {
  return (TRIGGERS as readonly string[]).includes(ch);
}

function rankFile(path: string, needle: string): number {
  if (!needle) return 0;
  const lower = path.toLowerCase();
  const idx = lower.indexOf(needle);
  if (idx < 0) return -1;
  // Prefer prefix matches at the basename level, then earlier path matches.
  const slash = lower.lastIndexOf("/", idx);
  const baseStart = slash < 0 ? 0 : slash + 1;
  if (idx === baseStart) return 0;
  if (lower.slice(baseStart).startsWith(needle)) return 1;
  return 2 + idx;
}

// Helper for tests: synthesize ExtensionEntry list so panels can render uniformly.
export function defaultExtensions(): ExtensionEntry[] {
  return [];
}
