import type { MentionCandidate, MentionDetection } from "../mentions";
import type { Theme } from "../theme";
import { makeBox, makeSelect, makeText } from "../layout";

export type MentionSelect = (candidate: MentionCandidate) => void;

const TRIGGER_TITLES: Record<string, string> = {
  "/": " slash commands ",
  "@": " files ",
  "$": " skills ",
};

export class MentionMenuWidget {
  readonly node: any;
  private select: any;
  private header: any;
  private candidates: MentionCandidate[] = [];
  private picker: MentionSelect | null = null;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "rounded",
      border: true,
      borderColor: theme.accent,
      paddingX: 1,
      paddingY: 0,
      backgroundColor: theme.surfaceMuted,
      visible: false,
      position: "absolute",
      bottom: 5,
      left: 2,
      width: 60,
      maxHeight: 10,
      zIndex: 75,
    });
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
      maxHeight: 8,
    });
    this.node.add?.(this.header);
    this.node.add?.(this.select);
    if (typeof this.select?.on === "function") {
      this.select.on("itemSelected", (event: any) => {
        const value = event?.value ?? event?.option?.value;
        if (!value) return;
        const candidate = this.candidates.find((item) => item.label === value);
        if (candidate && this.picker) this.picker(candidate);
      });
    }
  }

  open(detection: MentionDetection, candidates: MentionCandidate[], onPick: MentionSelect): void {
    this.candidates = candidates;
    this.picker = onPick;
    if (this.header && this.header.content !== undefined) {
      const trigger = TRIGGER_TITLES[detection.trigger] ?? " mention ";
      this.header.content = `${trigger.trim()} — "${detection.query}"`;
    }
    if (this.select && "options" in this.select) {
      this.select.options = candidates.length
        ? candidates.map((c) => ({ name: c.label, description: c.description ?? "", value: c.label }))
        : [{ name: "(no match)", description: "Type to filter or press Escape", value: "__none__" }];
    }
    if (this.node && "visible" in this.node) this.node.visible = candidates.length > 0;
  }

  refresh(detection: MentionDetection, candidates: MentionCandidate[]): void {
    this.candidates = candidates;
    if (this.header && this.header.content !== undefined) {
      const trigger = TRIGGER_TITLES[detection.trigger] ?? " mention ";
      this.header.content = `${trigger.trim()} — "${detection.query}"`;
    }
    if (this.select && "options" in this.select) {
      this.select.options = candidates.length
        ? candidates.map((c) => ({ name: c.label, description: c.description ?? "", value: c.label }))
        : [{ name: "(no match)", description: "Type to filter or press Escape", value: "__none__" }];
    }
    if (this.node && "visible" in this.node) this.node.visible = candidates.length > 0;
  }

  hide(): void {
    if (this.node && "visible" in this.node) this.node.visible = false;
    this.candidates = [];
    this.picker = null;
  }

  isVisible(): boolean {
    return Boolean(this.node?.visible);
  }

  candidateCount(): number {
    return this.candidates.length;
  }

  pickFirst(): void {
    if (!this.candidates.length || !this.picker) return;
    this.picker(this.candidates[0]);
  }

  moveUp(): void {
    this.select?.moveUp?.(1);
  }

  moveDown(): void {
    this.select?.moveDown?.(1);
  }

  /** Commit the currently highlighted candidate. */
  commit(): boolean {
    if (!this.candidates.length || !this.picker) return false;
    const index =
      typeof this.select?.getSelectedIndex === "function"
        ? this.select.getSelectedIndex()
        : 0;
    const candidate = this.candidates[index] ?? this.candidates[0];
    if (!candidate) return false;
    this.picker(candidate);
    return true;
  }
}
