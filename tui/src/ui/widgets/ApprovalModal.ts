import { glyphs } from "../../design/glyphs";
import type { Approval } from "../../protocol/events";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

// The only modal in the system (DESIGN_TOKENS.md §4.6). Heavy corners +
// danger border = "this blocks." No other surface uses this combination, so
// users can recognise the pattern at a glance even before reading the body.

export type ApprovalDecide = (decision: "approved" | "denied", approvalId: string) => void;

const APPROVAL_MODAL_WIDTH = 60;
const APPROVAL_DIVIDER_WIDTH = APPROVAL_MODAL_WIDTH - 10;

export class ApprovalModalWidget {
  readonly node: any;
  private backdrop: any;
  private dimContext: any;
  private titlePill: any;
  private toolLabel: any;
  private modal: any;
  private commandBox: any;
  private commandLine: any;
  private locationLine: any;
  private riskLine: any;
  private keyAllowOnce: any;
  private keyAllowSession: any;
  private keyDeny: any;
  private keyEdit: any;
  private hint: any;
  private approval: Approval | null = null;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      alignItems: "center",
      position: "absolute",
      top: 1,
      left: 0,
      right: 0,
      bottom: 0,
      width: "100%",
      height: "100%",
      paddingTop: 4,
      backgroundColor: "#07090DB8",
      visible: false,
      enableLayout: false,
      focusable: true,
      zIndex: 90,
    });

    // The Paper modal dims the conversation underneath, but terminal cells are
    // not alpha-composited text. Mask the raw transcript first, then draw a
    // controlled dim summary behind the blocking modal.
    this.backdrop = makeText(opentui, ctx, {
      content: blankBackdrop(),
      fg: theme.textSubtle,
      position: "absolute",
      top: 0,
      left: 0,
      zIndex: 90,
      enableLayout: false,
    });
    this.node.add?.(this.backdrop);

    this.dimContext = makeText(opentui, ctx, {
      content: "",
      fg: theme.borderStrong ?? theme.border,
      position: "absolute",
      top: 1,
      left: 2,
      zIndex: 90,
      enableLayout: false,
    });
    this.node.add?.(this.dimContext);

    // Danger outline + explicit heavy corner glyphs (DESIGN_TOKENS.md §4.6).
    // The full border stays thin so the modal reads like the Paper surface,
    // while the corner glyphs carry the blocking/danger weight.
    this.modal = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "single",
      border: true,
      borderColor: theme.borderDanger ?? theme.danger,
      paddingX: 3,
      paddingY: 1,
      backgroundColor: theme.surfaceModal ?? theme.surfaceMuted,
      width: APPROVAL_MODAL_WIDTH,
      flexShrink: 0,
      zIndex: 91,
    });
    this.node.add?.(this.modal);

    // Title row: ⦗ APPROVE ⦘ shell
    const titleRow = makeBox(opentui, ctx, { flexDirection: "row", marginBottom: 1 });
    titleRow.add?.(makeText(opentui, ctx, { content: "┏━", fg: theme.danger }));
    this.titlePill = makeText(opentui, ctx, {
      content: ` ${glyphs.pillL} APPROVE ${glyphs.pillR} `,
      fg: theme.danger,
      bg: theme.dangerSoft,
      marginLeft: 1,
    });
    this.toolLabel = makeText(opentui, ctx, { content: "", fg: theme.text, marginLeft: 1 });
    titleRow.add?.(this.titlePill);
    titleRow.add?.(this.toolLabel);
    titleRow.add?.(makeBox(opentui, ctx, { flexGrow: 1 }));
    titleRow.add?.(makeText(opentui, ctx, { content: "━┓", fg: theme.danger }));
    this.modal.add?.(titleRow);

    // Command card — sunken sub-surface so the command is the visual focus.
    this.commandBox = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "single",
      border: true,
      borderColor: theme.border,
      paddingX: 2,
      paddingY: 0,
      backgroundColor: theme.surfaceMuted,
      marginBottom: 1,
    });
    this.commandLine = makeText(opentui, ctx, { content: "", fg: theme.text });
    this.commandBox.add?.(this.commandLine);
    this.modal.add?.(this.commandBox);

    this.locationLine = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.modal.add?.(this.locationLine);
    this.riskLine = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.modal.add?.(this.riskLine);
    this.modal.add?.(
      makeText(opentui, ctx, {
        content: glyphs.dividerThin.repeat(APPROVAL_DIVIDER_WIDTH),
        fg: theme.border,
        marginTop: 1,
      }),
    );

    // Action grid — two columns. Color encodes intent; labels only advertise
    // decisions the wire protocol can resolve today.
    const k = (s: string) => `${glyphs.kbdL}${s}${glyphs.kbdR}`;
    const grid = makeBox(opentui, ctx, { flexDirection: "row" });
    const col1 = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    const col2 = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });

    this.keyAllowOnce = makeText(opentui, ctx, { content: `${k("y")} allow once`, fg: theme.text });
    this.keyAllowSession = makeText(opentui, ctx, { content: `${k("a")} allow for session`, fg: theme.text, marginTop: 0 });
    this.keyDeny = makeText(opentui, ctx, { content: `${k("n")} deny`, fg: theme.text });
    this.keyEdit = makeText(opentui, ctx, { content: `${k("e")} edit command`, fg: theme.textSubtle });

    col1.add?.(this.keyAllowOnce);
    col1.add?.(this.keyDeny);
    col2.add?.(this.keyAllowSession);
    col2.add?.(this.keyEdit);
    grid.add?.(col1);
    grid.add?.(col2);
    this.modal.add?.(grid);

    const hintRow = makeBox(opentui, ctx, { flexDirection: "row", marginTop: 1 });
    hintRow.add?.(makeText(opentui, ctx, { content: "┗━", fg: theme.danger }));
    this.hint = makeText(opentui, ctx, {
      content: "esc dismisses",
      fg: theme.textSubtle,
      marginLeft: 1,
    });
    hintRow.add?.(this.hint);
    hintRow.add?.(makeBox(opentui, ctx, { flexGrow: 1 }));
    hintRow.add?.(makeText(opentui, ctx, { content: "━┛", fg: theme.danger }));
    this.modal.add?.(hintRow);
  }

  setBackdropLines(lines: string[]): void {
    if (this.dimContext && this.dimContext.content !== undefined) {
      this.dimContext.content = lines.join("\n");
    }
  }

  setApproval(approval: Approval | null): void {
    this.approval = approval;
    if (this.node && "visible" in this.node) this.node.visible = Boolean(approval);
    if (this.node && "enableLayout" in this.node) this.node.enableLayout = Boolean(approval);
    if (!approval) return;
    if (this.toolLabel && this.toolLabel.content !== undefined) {
      this.toolLabel.content = approval.tool_name;
    }
    if (this.commandLine && this.commandLine.content !== undefined) {
      this.commandLine.content = approval.command ? approval.command : approval.args_preview;
    }
    if (this.locationLine && this.locationLine.content !== undefined) {
      const cwd = (approval as any).cwd ?? "";
      this.locationLine.content = cwd ? `in: ${cwd}` : "";
    }
    if (this.riskLine && this.riskLine.content !== undefined) {
      this.riskLine.content = approval.turn_id ? `requested by: agent · ${approval.turn_id}` : approval.risk ? `risk: ${approval.risk}` : "";
    }
  }

  current(): Approval | null {
    return this.approval;
  }

  setOnDecide(handler: ApprovalDecide): void {
    if (!this.node) return;
    this.node.onKeyDown = (key: { name?: string; sequence?: string }) => {
      if (!this.approval) return;
      const name = (key.name ?? key.sequence ?? "").toLowerCase();
      // y/a both approve; treat `a` as session-allow upstream when supported,
      // but for the wire protocol both map to "approved" today.
      if (name === "a" || name === "y") handler("approved", this.approval.approval_id);
      else if (name === "d" || name === "n") handler("denied", this.approval.approval_id);
      else if (name === "escape") handler("denied", this.approval.approval_id);
    };
  }
}

function blankBackdrop(width = 180, height = 60): string {
  // NBSP is visually blank but not treated like a transparent ASCII space by
  // OpenTUI's character capture.
  const line = "\u00a0".repeat(width);
  return Array.from({ length: height }, () => line).join("\n");
}
