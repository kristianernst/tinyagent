import type { Conversation } from "../../protocol/events";
import type { Theme } from "../theme";
import { makeBox, makeSelect, makeText } from "../layout";

export class SessionsWidget {
  readonly node: any;
  private select: any;
  private detail: any;
  private items: Conversation[] = [];

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
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
      flexGrow: 1,
      minHeight: 4,
    });
    this.detail = makeText(opentui, ctx, { content: "No sessions.", fg: theme.textMuted, marginTop: 1 });
    this.node.add?.(this.select);
    this.node.add?.(this.detail);
    if (typeof this.select?.on === "function") {
      this.select.on("selectionChanged", (event: any) => {
        const index = event?.index ?? event?.selectedIndex ?? 0;
        this.renderDetail(this.items[index]);
      });
    }
  }

  update(sessions: Conversation[]): void {
    this.items = sessions;
    if (!sessions.length) {
      if (this.select && "options" in this.select) this.select.options = [];
      if (this.detail && this.detail.content !== undefined) this.detail.content = "No sessions.";
      return;
    }
    if (this.select && "options" in this.select) {
      this.select.options = sessions.map((session) => ({
        name: `${session.status.padEnd(8)} ${session.title || session.conversation_id}`,
        description: `${session.turn_count} turns · ${session.updated_at}`,
        value: session.conversation_id,
      }));
    }
    this.renderDetail(sessions[0]);
  }

  private renderDetail(session: Conversation | undefined): void {
    if (!session) {
      if (this.detail && this.detail.content !== undefined) this.detail.content = "";
      return;
    }
    const lines = [
      `id: ${session.conversation_id}`,
      `title: ${session.title || "(untitled)"}`,
      `status: ${session.status}`,
      `workspace: ${session.workspace}`,
      `turns: ${session.turn_count}`,
      `created: ${session.created_at}`,
      `updated: ${session.updated_at}`,
      session.last_run_id ? `last run: ${session.last_run_id}` : "",
      session.last_turn_status ? `last turn: ${session.last_turn_status}` : "",
    ].filter(Boolean);
    if (this.detail && this.detail.content !== undefined) this.detail.content = lines.join("\n");
  }
}
