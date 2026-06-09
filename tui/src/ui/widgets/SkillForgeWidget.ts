import type { SkillDraft } from "../../protocol/events";
import type { SkillForgeState } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";
import { InfoPanelWidget } from "./InfoPanelWidget";
import { makePanelList } from "./panelStyle";

export class SkillForgeWidget {
  readonly node: any;
  private header: InfoPanelWidget;
  private select: any;
  private preview: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.header = new InfoPanelWidget(opentui, ctx, theme, { compact: true, minHeight: 9 });
    this.select = makePanelList(opentui, ctx, theme, {
      showDescription: true,
      minHeight: 4,
      height: 7,
      flexShrink: 0,
      marginTop: 1,
      maxRows: 3,
      maxTextWidth: 52,
    });
    this.preview = makeText(opentui, ctx, {
      content: "",
      fg: theme.assistant,
      flexGrow: 1,
      marginTop: 1,
    });
    this.node.add?.(this.header.node);
    this.node.add?.(this.select);
    this.node.add?.(this.preview);
  }

  update(skillForge: SkillForgeState): void {
    const selected = skillForge.drafts.find((draft) => draft.draft_id === skillForge.selectedDraftId);
    this.header.update({
      eyebrow: "skill forge",
      rows: [
        {
          label: "status",
          value: skillForge.status,
          detail: skillForge.error || `${skillForge.drafts.length} draft${skillForge.drafts.length === 1 ? "" : "s"} loaded`,
          tone: skillForge.error ? "danger" : skillForge.status === "ready" ? "success" : "muted",
        },
        {
          label: "draft",
          value: selected?.name || skillForge.selectedDraftId || "none",
          detail: selected ? selected.path : skillForge.lastAction || "select a draft to preview",
        },
      ],
    });
    if (this.select && "options" in this.select) {
      this.select.options = skillForge.drafts.map((draft) => ({
        name: draft.name,
        rightMeta: draft.status,
        description: draftDetail(draft),
        value: draft.draft_id,
      }));
    }
    if (this.preview && this.preview.content !== undefined) {
      this.preview.content = skillPreview(skillForge.markdown, selected);
    }
  }
}

function skillPreview(markdown: string, selected?: SkillDraft): string {
  if (!markdown) {
    return ["draft preview", previewRow("preview", "pending", selected?.path || "load draft markdown")].join("\n");
  }
  const summary = summarizeMarkdown(markdown);
  const rows = [
    "draft preview",
    previewRow("name", summary.title || selected?.name || "draft", selected?.path || "SKILL.md"),
  ];
  if (summary.purpose) rows.push(previewRow("purpose", summary.purpose, "draft intent"));
  summary.steps.forEach((step, index) => rows.push(previewRow(`step ${index + 1}`, step, `${index + 1} of ${summary.steps.length}`)));
  return rows.join("\n");
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

function previewRow(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${truncate(value, 40)}`, `    ${truncate(detail, 58)}`].join("\n");
}

function draftDetail(draft: SkillDraft): string {
  return `${draft.path} · ${sourceRunLabel(draft.source_run_id)}`;
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

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, Math.max(0, max - 1))}…`;
}
