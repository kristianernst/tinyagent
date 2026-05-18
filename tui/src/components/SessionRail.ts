import type { Conversation } from "../protocol/events";

export function renderSessionRail(sessions: Conversation[]): string {
  if (!sessions.length) return "No sessions.";
  return sessions.map((session) => `${session.status.padEnd(8)} ${session.conversation_id} ${session.title}`).join("\n");
}
