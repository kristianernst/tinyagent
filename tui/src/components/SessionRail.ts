import type { Conversation } from "../protocol/events";

export function renderSessionRail(sessions: Conversation[]): string {
  if (!sessions.length) return ["sessions", row("status", "empty", "no saved sessions")].join("\n");
  return ["sessions", ...sessions.map((session) => sessionRow(session))].join("\n");
}

function sessionRow(session: Conversation): string {
  return row(sessionTitle(session), sessionStatus(session), sessionMeta(session));
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}

function sessionTitle(session: Conversation): string {
  const title = String(session.title || "").trim();
  if (title) return title;
  const cleaned = String(session.conversation_id || "")
    .replace(/^conv[_-]?/i, "")
    .replace(/[_-]+/g, " ")
    .trim();
  return cleaned || "saved session";
}

function sessionStatus(session: Conversation): string {
  return String(session.status || "saved");
}

function sessionMeta(session: Conversation): string {
  const parts = [
    sessionModel(session),
    `${session.turn_count} turn${session.turn_count === 1 ? "" : "s"}`,
    sessionTokens(session),
    String(session.updated_at || "").trim(),
  ].filter(Boolean);
  return parts.join(" · ") || "session history";
}

function sessionModel(session: Conversation): string {
  const value = (session as any).model ?? (session as any).model_name ?? (session as any).provider;
  return typeof value === "string" && value ? value : session.workspace || "workspace";
}

function sessionTokens(session: Conversation): string {
  const raw = (session as any).tokens ?? (session as any).token_count ?? (session as any).total_tokens ?? (session as any).totalTokens;
  const value = typeof raw === "number" ? raw : Number(raw);
  if (!Number.isFinite(value) || value <= 0) return "";
  if (value >= 1000) return `${Number((value / 1000).toFixed(1))}k tok`;
  return `${value} tok`;
}
