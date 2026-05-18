import type { Approval } from "../../protocol/events";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export type ApprovalDecide = (decision: "approved" | "denied", approvalId: string) => void;

export class ApprovalModalWidget {
  readonly node: any;
  private title: any;
  private toolLine: any;
  private riskLine: any;
  private commandLine: any;
  private hint: any;
  private approval: Approval | null = null;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      flexDirection: "column",
      borderStyle: "double",
      border: true,
      borderColor: theme.warning,
      paddingX: 2,
      paddingY: 1,
      backgroundColor: theme.surfaceMuted,
      title: " Approval required ",
      visible: false,
      focusable: true,
      position: "absolute",
      top: 4,
      left: 8,
      right: 8,
      zIndex: 90,
    });
    this.title = makeText(opentui, ctx, { content: "", fg: theme.warning });
    this.toolLine = makeText(opentui, ctx, { content: "", fg: theme.text });
    this.riskLine = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.commandLine = makeText(opentui, ctx, { content: "", fg: theme.assistant });
    this.hint = makeText(opentui, ctx, {
      content: "[A] approve · [D] deny · Esc to dismiss",
      fg: theme.textSubtle,
    });
    this.node.add?.(this.title);
    this.node.add?.(this.toolLine);
    this.node.add?.(this.riskLine);
    this.node.add?.(this.commandLine);
    this.node.add?.(this.hint);
  }

  setApproval(approval: Approval | null): void {
    this.approval = approval;
    if (this.node && "visible" in this.node) this.node.visible = Boolean(approval);
    if (!approval) return;
    if (this.title && this.title.content !== undefined) this.title.content = `Tool: ${approval.tool_name}`;
    if (this.toolLine && this.toolLine.content !== undefined) this.toolLine.content = `Action: ${approval.action_kind}`;
    if (this.riskLine && this.riskLine.content !== undefined) this.riskLine.content = `Risk: ${approval.risk}`;
    if (this.commandLine && this.commandLine.content !== undefined) {
      this.commandLine.content = approval.command ? `$ ${approval.command}` : approval.args_preview;
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
      if (name === "a" || name === "y") handler("approved", this.approval.approval_id);
      else if (name === "d" || name === "n") handler("denied", this.approval.approval_id);
    };
  }
}
