import type { SkillForgeState } from "../state/reducer";

export function renderSkillForge(skillForge: SkillForgeState): string {
  const rows = skillForge.drafts.map((draft) => `${draft.draft_id.padEnd(28)} ${draft.status.padEnd(8)} ${draft.name}`);
  return [
    `Status: ${skillForge.status}`,
    skillForge.lastAction ? `Last: ${skillForge.lastAction}` : "",
    skillForge.error ? `Error: ${skillForge.error}` : "",
    rows.length ? "\nDraft                       Status   Name" : "No drafts.",
    ...rows,
    skillForge.selectedDraftId ? `\nSelected: ${skillForge.selectedDraftId}` : "",
    skillForge.markdown ? skillForge.markdown.split("\n").slice(0, 16).join("\n") : "",
  ]
    .filter(Boolean)
    .join("\n");
}
