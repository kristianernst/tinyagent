import type { SkillForgeState } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeMarkdown, makeSelect, makeText, syntaxStyleFor } from "../layout";

export class SkillForgeWidget {
  readonly node: any;
  private header: any;
  private select: any;
  private preview: any;
  private syntaxStyle: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.syntaxStyle = syntaxStyleFor(opentui, theme);
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.header = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.select = makeSelect(opentui, ctx, {
      options: [],
      showDescription: true,
      backgroundColor: theme.surface,
      textColor: theme.text,
      selectedBackgroundColor: theme.selectionBg,
      selectedTextColor: theme.selectionFg,
      descriptionColor: theme.textMuted,
      selectedDescriptionColor: theme.text,
      showScrollIndicator: true,
      wrapSelection: true,
      focusable: true,
      minHeight: 4,
      marginTop: 1,
    });
    this.preview = makeMarkdown(opentui, ctx, {
      content: "",
      syntaxStyle: this.syntaxStyle,
      fg: theme.assistant,
      flexGrow: 1,
      marginTop: 1,
    });
    this.node.add?.(this.header);
    this.node.add?.(this.select);
    this.node.add?.(this.preview);
  }

  update(skillForge: SkillForgeState): void {
    if (this.header && this.header.content !== undefined) {
      this.header.content = [
        `Status: ${skillForge.status}`,
        skillForge.lastAction ? `Last: ${skillForge.lastAction}` : "",
        skillForge.error ? `Error: ${skillForge.error}` : "",
        skillForge.selectedDraftId ? `Selected: ${skillForge.selectedDraftId}` : "",
      ]
        .filter(Boolean)
        .join("\n");
    }
    if (this.select && "options" in this.select) {
      this.select.options = skillForge.drafts.map((draft) => ({
        name: `${draft.status.padEnd(8)} ${draft.name}`,
        description: `${draft.draft_id} · ${draft.source_run_id}`,
        value: draft.draft_id,
      }));
    }
    if (this.preview && this.preview.content !== undefined) {
      this.preview.content = skillForge.markdown || "Select a draft and /skills show <id> to preview.";
    }
  }
}
