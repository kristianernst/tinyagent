import { pickerCommands } from "../commands";
import type { ExtensionEntry, MentionTrigger, SkillEntry, WorkspaceFileMetadata } from "../state/reducer";

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
  meta?: string;
  disabled?: boolean;
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
  const matches = (command: (typeof pickerCommands)[number]) => !needle || command.id.includes(needle) || command.title.toLowerCase().includes(needle);
  if (!pickerCommands.some(matches)) return [];
  return pickerCommands.map((command) => ({
    label: `/${command.id}`,
    description: command.title,
    insert: `/${command.id} `,
  }));
}

export function candidatesForFile(query: string, files: string[], metadata: WorkspaceFileMetadata = {}): MentionCandidate[] {
  const needle = query.toLowerCase();
  const ranked = files
    .map((path) => ({ path, score: rankFile(path, needle) }))
    .filter((row) => row.score >= 0)
    .sort((a, b) => a.score - b.score)
    .slice(0, 12);
  const matches = ranked.map(({ path }) => fileCandidate(path, metadata));
  const recent = needle && matches.length > 0 ? recentFile(files, new Set(ranked.map((row) => row.path)), metadata) : "";
  if (!recent) return matches;
  return [
    ...matches,
    { label: "— recent —", insert: "", disabled: true },
    fileCandidate(recent, metadata),
  ];
}

export function candidatesForSkill(query: string, skills: SkillEntry[]): MentionCandidate[] {
  const needle = query.toLowerCase();
  const matches = (skill: SkillEntry) => !needle || skill.name.toLowerCase().includes(needle);
  if (!skills.some(matches)) return [];
  return skills.map((skill) => ({
    label: `$${skill.name}`,
    description: skillPickerDescription(skill),
    insert: `$${skill.name} `,
  }));
}

export function pickCandidates(
  detection: MentionDetection,
  files: string[],
  skills: SkillEntry[],
  options: { fileMetadata?: WorkspaceFileMetadata } = {},
): MentionCandidate[] {
  switch (detection.trigger) {
    case "/":
      return candidatesForSlash(detection.query);
    case "@":
      return candidatesForFile(detection.query, files, options.fileMetadata);
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

function fileCandidate(path: string, metadata: WorkspaceFileMetadata): MentionCandidate {
  const meta = metadata[path];
  return {
    label: path,
    description: "",
    insert: `@${path} `,
    meta: typeof meta?.bytes === "number" ? formatBytes(meta.bytes) : undefined,
  };
}

function recentFile(files: string[], matched: Set<string>, metadata: WorkspaceFileMetadata): string {
  return files
    .filter((path) => !matched.has(path) && typeof metadata[path]?.mtimeMs === "number")
    .sort((a, b) => (metadata[b]?.mtimeMs ?? 0) - (metadata[a]?.mtimeMs ?? 0))[0] ?? "";
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${Math.max(0, Math.round(bytes))}b`;
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))}kb`;
  return `${Math.max(1, Math.round(bytes / (1024 * 1024)))}mb`;
}

function skillPickerDescription(skill: SkillEntry): string {
  const raw = (skill.description || skill.path || "skill").trim().replace(/\s+/g, " ");
  const compact = raw
    .replace(/\bOpenTUI\b/g, "TUI")
    .replace(/\bthe terminal surface\b/gi, "terminal")
    .replace(/\bterminal surface\b/gi, "terminal")
    .replace(/\bthe Paper artboard\b/g, "Paper")
    .replace(/\bPaper artboard\b/g, "Paper");
  const before = compact.match(/^(.+?)\s+before\s+/i);
  const candidate = before?.[1] ?? compact;
  if (candidate.length <= 32) return lowerFirst(candidate);
  return lowerFirst(candidate.split(/\s+/).slice(0, 4).join(" "));
}

function lowerFirst(value: string): string {
  if (!value) return value;
  return `${value[0]!.toLowerCase()}${value.slice(1)}`;
}

// Helper for tests: synthesize ExtensionEntry list so panels can render uniformly.
export function defaultExtensions(): ExtensionEntry[] {
  return [];
}
