export type RunEvent = {
  id: string;
  seq: number;
  type: string;
  time: string;
  run_id: string;
  turn_id: string | null;
  item_id: string | null;
  parent_item_id: string | null;
  source: string;
  visibility: "internal" | "debug" | "user" | "public";
  durability: "ephemeral" | "event_log" | "artifact_only";
  data: Record<string, any>;
  artifact_refs: string[];
};

export type StartConversationTurnResponse = {
  run_id: string;
  run_path: string;
  status: string;
  conversation_id?: string;
  turn_id?: string;
};

export type ConversationSummary = {
  conversation_id: string;
  title: string;
  status: "open" | "closed";
  active_turn_id: string | null;
  created_at: string;
  updated_at: string;
  workspace: string;
  turn_count: number;
  last_run_id?: string;
  last_turn_status?: string;
};

export type WorkspaceSummary = {
  workspace_id: string;
  name: string;
  root: string;
  kind: string;
  trust: string;
  default_provider: string;
  updated_at: string;
  last_opened_at: string;
};

export type ApprovalDecision = "approved" | "denied" | "cancelled" | "expired";

const BASE = "/api";

export class TinyagentClient {
  constructor(private readonly base = BASE) {}

  async listWorkspaces(): Promise<WorkspaceSummary[]> {
    const res = await fetch(`${this.base}/workspaces`);
    if (!res.ok) {
      throw new Error(`listWorkspaces failed: ${res.status} ${await res.text()}`);
    }
    const body = await res.json();
    return Array.isArray(body.workspaces) ? body.workspaces : [];
  }

  async registerWorkspace(path: string, name?: string): Promise<WorkspaceSummary> {
    const res = await fetch(`${this.base}/workspaces`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, name }),
    });
    if (!res.ok) {
      throw new Error(`registerWorkspace failed: ${res.status} ${await res.text()}`);
    }
    const body = await res.json();
    return body.workspace as WorkspaceSummary;
  }

  async listConversations(workspaceId: string): Promise<ConversationSummary[]> {
    const res = await fetch(`${this.base}/conversations?workspace_id=${encodeURIComponent(workspaceId)}`);
    if (!res.ok) {
      throw new Error(`listConversations failed: ${res.status} ${await res.text()}`);
    }
    const body = await res.json();
    return Array.isArray(body.conversations) ? body.conversations : [];
  }

  async startConversationTurn(
    workspaceId: string,
    conversationId: string,
    message: string,
    opts: {
      run_id?: string;
      approval_mode?: "yolo" | "on-request" | "never";
      turn_id?: string;
      parent_turn_id?: string;
    } = {}
  ): Promise<StartConversationTurnResponse> {
    const res = await fetch(`${this.base}/conversations/${encodeURIComponent(conversationId)}/turns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_id: workspaceId, message, ...opts }),
    });
    if (!res.ok) {
      throw new Error(`startConversationTurn failed: ${res.status} ${await res.text()}`);
    }
    return res.json();
  }

  async cancelRun(workspaceId: string, runId: string, reason = "user_cancelled"): Promise<boolean> {
    const res = await fetch(`${this.base}/runs/${encodeURIComponent(runId)}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_id: workspaceId, reason }),
    });
    if (!res.ok) return false;
    const body = await res.json();
    return !!body.cancelled;
  }

  async decideApproval(
    workspaceId: string,
    runId: string,
    approvalId: string,
    decision: ApprovalDecision,
    scope: "once" | "run" | null = "once"
  ): Promise<boolean> {
    const res = await fetch(`${this.base}/runs/${encodeURIComponent(runId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace_id: workspaceId, approval_id: approvalId, decision, scope }),
    });
    if (!res.ok) return false;
    const body = await res.json();
    return !!body.resolved;
  }

  async fetchArtifactText(workspaceId: string, runId: string, path: string): Promise<string> {
    const segments = path.split("/").map(encodeURIComponent).join("/");
    const res = await fetch(
      `${this.base}/runs/${encodeURIComponent(runId)}/artifacts/${segments}?workspace_id=${encodeURIComponent(workspaceId)}`
    );
    if (!res.ok) {
      throw new Error(`artifact fetch failed: ${res.status}`);
    }
    return res.text();
  }

  async fetchRunEvents(workspaceId: string, runId: string, afterSeq = 0): Promise<RunEvent[]> {
    const params = new URLSearchParams({ workspace_id: workspaceId });
    if (afterSeq > 0) params.set("after_seq", String(afterSeq));
    const res = await fetch(`${this.base}/runs/${encodeURIComponent(runId)}/events.json?${params.toString()}`);
    if (!res.ok) {
      throw new Error(`fetchRunEvents failed: ${res.status} ${await res.text()}`);
    }
    const body = await res.json();
    return Array.isArray(body.events) ? body.events : [];
  }

  streamRunEvents(
    workspaceId: string,
    runId: string,
    onEvent: (event: RunEvent) => void,
    opts: { afterSeq?: number; onError?: (err: unknown) => void; onClose?: () => void } = {}
  ): AbortController {
    const ctrl = new AbortController();
    const params = new URLSearchParams({ workspace_id: workspaceId });
    if (opts.afterSeq) params.set("after_seq", String(opts.afterSeq));
    (async () => {
      try {
        const res = await fetch(`${this.base}/runs/${encodeURIComponent(runId)}/events?${params.toString()}`, {
          signal: ctrl.signal,
          headers: { Accept: "text/event-stream" },
        });
        if (!res.ok || !res.body) {
          throw new Error(`stream failed: ${res.status}`);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buf = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx;
          while ((idx = buf.indexOf("\n\n")) !== -1) {
            const block = buf.slice(0, idx);
            buf = buf.slice(idx + 2);
            const ev = parseSseBlock(block);
            if (ev) onEvent(ev);
          }
        }
      } catch (err) {
        if ((err as any)?.name === "AbortError") return;
        opts.onError?.(err);
      } finally {
        opts.onClose?.();
      }
    })();
    return ctrl;
  }
}

export const tinyagent = new TinyagentClient();

function parseSseBlock(block: string): RunEvent | null {
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (dataLines.length === 0) return null;
  try {
    return JSON.parse(dataLines.join("\n")) as RunEvent;
  } catch {
    return null;
  }
}
