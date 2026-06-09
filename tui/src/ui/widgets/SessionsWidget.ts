import type { Conversation } from "../../protocol/events";
import { glyphs } from "../../design/glyphs";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export class SessionsWidget {
  readonly node: any;
  private select: any;
  private empty: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.select = makeSessionList(opentui, ctx, theme, {
      flexGrow: 1,
      minHeight: 4,
      maxRows: 6,
    });
    this.empty = makeText(opentui, ctx, { content: "sessions\n  ▏ status        empty\n    no saved sessions", fg: theme.textMuted });
    this.node.add?.(this.select);
    this.node.add?.(this.empty);
  }

  selectedConversationId(): string {
    return this.select?.selectedValue?.() ?? "";
  }

  setViewportWidth(width: number): void {
    if (this.select && "lineWidth" in this.select) this.select.lineWidth = Math.max(32, width - 8);
  }

  update(sessions: Conversation[]): void {
    if (!sessions.length) {
      if (this.select && "sessions" in this.select) this.select.sessions = [];
      if (this.empty && "visible" in this.empty) this.empty.visible = true;
      if (this.empty && "enableLayout" in this.empty) this.empty.enableLayout = true;
      return;
    }
    if (this.empty && "visible" in this.empty) this.empty.visible = false;
    if (this.empty && "enableLayout" in this.empty) this.empty.enableLayout = false;
    if (this.select && "sessions" in this.select) this.select.sessions = sessions;
  }
}

type SessionListProps = {
  flexGrow?: number;
  minHeight?: number;
  maxRows?: number;
};

type SessionListEvent = "selectionChanged" | "itemSelected";
type SessionListHandler = (event: { index: number; selectedIndex: number; session?: Conversation; value?: string }) => void;

function makeSessionList(opentui: any, ctx: any, theme: Theme, props: SessionListProps = {}): any {
  const { maxRows = 6, ...layout } = props;
  const node = makeBox(opentui, ctx, {
    flexDirection: "column",
    backgroundColor: theme.surfaceOverlay ?? theme.surface,
    focusable: true,
    ...layout,
  });
  const handlers = new Map<SessionListEvent, SessionListHandler[]>();
  const rows: any[] = [];
  let sessions: Conversation[] = [];
  let selectedIndex = 0;
  let hoverIndex: number | null = null;
  let lineWidth = 52;

  const emit = (event: SessionListEvent) => {
    const session = sessions[selectedIndex];
    for (const handler of handlers.get(event) ?? []) {
      handler({ index: selectedIndex, selectedIndex, session, value: session?.conversation_id });
    }
  };

  const clearRows = () => {
    for (const row of rows.splice(0)) node.remove?.(row.id ?? row);
  };

  const render = () => {
    clearRows();
    const visibleStart = Math.min(Math.max(0, selectedIndex - maxRows + 1), Math.max(0, sessions.length - maxRows));
    const visible = sessions.slice(visibleStart, visibleStart + maxRows);
    for (let localIndex = 0; localIndex < visible.length; localIndex++) {
      const index = visibleStart + localIndex;
      const session = visible[localIndex]!;
      const selected = index === selectedIndex;
      const hovered = index === hoverIndex && !selected;
      const row = makeBox(opentui, ctx, {
        flexDirection: "column",
        minHeight: 2,
        paddingX: 1,
        backgroundColor: selected ? theme.selectionBg : hovered ? theme.rowHoverBg : theme.surfaceOverlay ?? theme.surface,
        focusable: true,
        cursor: "pointer",
      });
      const lines = renderSessionLines(session, selected, lineWidth);
      row.add?.(
        makeText(opentui, ctx, {
          content: lines.title,
          fg: selected ? theme.selectionFg : hovered ? theme.rowHoverFg : theme.text,
        }),
      );
      row.add?.(
        makeText(opentui, ctx, {
          content: lines.meta,
          fg: selected ? theme.text : theme.textMuted,
        }),
      );
      row.onMouseOver = () => {
        if (hoverIndex === index) return;
        hoverIndex = index;
        render();
      };
      row.onMouseOut = () => {
        if (hoverIndex !== index) return;
        hoverIndex = null;
        render();
      };
      row.onMouseDown = (event: any) => {
        if (event?.type !== "down" || (event.button !== 0 && event.button != null)) return;
        hoverIndex = null;
        selectedIndex = index;
        render();
        emit("selectionChanged");
      };
      node.add?.(row);
      rows.push(row);
    }
  };

  const move = (delta: number) => {
    if (!sessions.length) return false;
    selectedIndex = (selectedIndex + delta + sessions.length) % sessions.length;
    render();
    emit("selectionChanged");
    return true;
  };

  Object.defineProperty(node, "sessions", {
    get: () => sessions,
    set: (next: Conversation[]) => {
      sessions = Array.isArray(next) ? next : [];
      selectedIndex = Math.min(selectedIndex, Math.max(0, sessions.length - 1));
      hoverIndex = null;
      render();
    },
    configurable: true,
  });
  Object.defineProperty(node, "lineWidth", {
    get: () => lineWidth,
    set: (next: number) => {
      lineWidth = Math.max(32, Math.min(72, Math.floor(Number.isFinite(next) ? next : 52)));
      render();
    },
    configurable: true,
  });
  node.on = (event: SessionListEvent, handler: SessionListHandler) => {
    handlers.set(event, [...(handlers.get(event) ?? []), handler]);
  };
  node.off = (event: SessionListEvent, handler: SessionListHandler) => {
    handlers.set(event, (handlers.get(event) ?? []).filter((item) => item !== handler));
  };
  node.moveUp = () => move(-1);
  node.moveDown = () => move(1);
  node.commit = () => {
    if (!sessions.length) return false;
    emit("itemSelected");
    return true;
  };
  node.selectedValue = () => sessions[selectedIndex]?.conversation_id ?? "";
  render();
  return node;
}

function renderSessionLines(session: Conversation, selected: boolean, lineWidth: number): { title: string; meta: string } {
  const marker = selected ? `${glyphs.caretStream} ` : "  ";
  const status = String(session.status || "");
  const updated = String(session.updated_at || "");
  const right = selected && status ? status : updated || status;
  const title = withRightMeta(`${marker}${truncate(session.title || session.conversation_id, Math.max(18, lineWidth - 12))}`, right, lineWidth);
  const metaParts = [
    sessionModel(session),
    `${session.turn_count} turn${session.turn_count === 1 ? "" : "s"}`,
    sessionTokens(session),
  ].filter(Boolean);
  const withUpdated = selected && updated ? [...metaParts, updated] : metaParts;
  const meta = `  ${withUpdated.join(" · ")}`;
  return {
    title,
    meta: meta.length <= lineWidth ? meta : `  ${metaParts.join(" · ")}`,
  };
}

function sessionModel(session: Conversation): string {
  const value = (session as any).model ?? (session as any).model_name ?? (session as any).provider;
  return typeof value === "string" && value ? value : session.workspace || "workspace";
}

function sessionTokens(session: Conversation): string {
  const raw = (session as any).tokens ?? (session as any).token_count ?? (session as any).total_tokens ?? (session as any).totalTokens;
  const value = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(value) || value <= 0) return "";
  if (value >= 1000) return `${Number((value / 1000).toFixed(value >= 10_000 ? 1 : 1))}k tok`;
  return `${value} tok`;
}

function withRightMeta(left: string, meta: string, width: number): string {
  if (!meta) return left;
  const gap = 2;
  const maxLeft = Math.max(0, width - meta.length - gap);
  const clipped = truncate(left, maxLeft);
  return `${clipped}${" ".repeat(Math.max(gap, width - clipped.length - meta.length))}${meta}`;
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, Math.max(0, max - 1))}…`;
}
