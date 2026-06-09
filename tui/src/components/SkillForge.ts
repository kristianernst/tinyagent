import type { SkillForgeState } from "../state/reducer";

export function renderSkillForge(skillForge: SkillForgeState): string {
  const selected = skillForge.drafts.find((draft) => draft.draft_id === skillForge.selectedDraftId);
  const rows = skillForge.drafts.map((draft) => row(draftTitle(draft), draft.status, `${draft.path} · ${sourceRunLabel(draft.source_run_id)}`));
  return [
    "skill forge",
    row("status", skillForge.status, `${skillForge.drafts.length} draft${skillForge.drafts.length === 1 ? "" : "s"} loaded`),
    skillForge.error ? row("error", skillForge.error, "needs attention") : "",
    rows.length ? ["drafts", ...rows].join("\n") : row("drafts", "empty", "no drafts"),
    selected ? row("draft", draftTitle(selected), selected.path) : "",
    skillPreview(skillForge.markdown, selected),
  ]
    .filter(Boolean)
    .join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}

function skillPreview(markdown: string, selected?: SkillForgeState["drafts"][number]): string {
  if (!markdown) return ["draft preview", row("preview", "pending", selected?.path || "load draft markdown")].join("\n");
  const summary = summarizeMarkdown(markdown);
  const rows = [
    "draft preview",
    row("name", summary.title || (selected ? draftTitle(selected) : "draft"), selected?.path || "SKILL.md"),
  ];
  if (summary.purpose) rows.push(row("purpose", summary.purpose, "draft intent"));
  summary.steps.forEach((step, index) => rows.push(row(`step ${index + 1}`, step, `${index + 1} of ${summary.steps.length}`)));
  return rows.join("\n");
}

function draftTitle(draft: SkillForgeState["drafts"][number]): string {
  const title = String(draft.name || "").trim();
  if (title) return title;
  const clean = draft.draft_id.replace(/^draft[_-]?/i, "").replace(/[_-]+/g, " ").trim();
  return clean || "skill draft";
}

function summarizeMarkdown(markdown: string): { title: string; purpose: string; steps: string[] } {
  const lines = markdown
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  const title = stripMarkdown(lines.find((line) => line.startsWith("#")) ?? "");
  const purpose = compactPurpose(stripMarkdown(lines.find((line) => !line.startsWith("#") && !line.startsWith("-")) ?? ""));
  const steps = lines
    .filter((line) => line.startsWith("-"))
    .slice(0, 3)
    .map((line) => compactStep(stripMarkdown(line.replace(/^-+\s*/, ""))));
  return { title, purpose, steps };
}

function sourceRunLabel(runId: string): string {
  const clean = runId.replace(/^run[_-]?/i, "").replace(/[_-]+/g, " ").trim();
  return clean || "source";
}

function stripMarkdown(value: string): string {
  return value.replace(/^#+\s*/, "").replace(/\*\*/g, "").trim();
}

function compactPurpose(value: string): string {
  return value.replace(/^For\s+/i, "").replace(/\.$/, "").trim();
}

function compactStep(value: string): string {
  return value.replace(/\s+before calling the work done\.?$/i, "").trim();
}
