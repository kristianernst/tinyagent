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

export type StartRunResponse = {
  run_id: string;
  run_path: string;
  status: string;
  session_id?: string;
  turn_id?: string;
};

export type SessionSummary = {
  session_id: string;
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

export type ApprovalDecision = "approved" | "denied" | "cancelled" | "expired";

const BASE = "/api";

export async function startRun(
  task: string,
  opts: {
    run_id?: string;
    approval_mode?: "yolo" | "on-request" | "never";
    session_id?: string;
    turn_id?: string;
    parent_turn_id?: string;
  } = {}
): Promise<StartRunResponse> {
  const res = await fetch(`${BASE}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, ...opts }),
  });
  if (!res.ok) {
    throw new Error(`startRun failed: ${res.status} ${await res.text()}`);
  }
  return res.json();
}

export async function cancelRun(runId: string, reason = "user_cancelled"): Promise<boolean> {
  const res = await fetch(`${BASE}/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) return false;
  const body = await res.json();
  return !!body.cancelled;
}

export async function decideApproval(
  runId: string,
  approvalId: string,
  decision: ApprovalDecision,
  scope: "once" | "run" | null = "once"
): Promise<boolean> {
  const res = await fetch(`${BASE}/runs/${encodeURIComponent(runId)}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approval_id: approvalId, decision, scope }),
  });
  if (!res.ok) return false;
  const body = await res.json();
  return !!body.resolved;
}

export async function fetchArtifactText(runId: string, path: string): Promise<string> {
  const segments = path.split("/").map(encodeURIComponent).join("/");
  const res = await fetch(`${BASE}/runs/${encodeURIComponent(runId)}/artifacts/${segments}`);
  if (!res.ok) {
    throw new Error(`artifact fetch failed: ${res.status}`);
  }
  return res.text();
}

export async function listSessions(): Promise<SessionSummary[]> {
  const res = await fetch(`${BASE}/sessions`);
  if (!res.ok) {
    throw new Error(`listSessions failed: ${res.status} ${await res.text()}`);
  }
  const body = await res.json();
  return Array.isArray(body.sessions) ? body.sessions : [];
}

export async function fetchRunEvents(runId: string, afterSeq = 0): Promise<RunEvent[]> {
  const url = `${BASE}/runs/${encodeURIComponent(runId)}/events.json${
    afterSeq > 0 ? `?after_seq=${afterSeq}` : ""
  }`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`fetchRunEvents failed: ${res.status} ${await res.text()}`);
  }
  const body = await res.json();
  return Array.isArray(body.events) ? body.events : [];
}

/**
 * Stream a run's SSE events using fetch + ReadableStream so every named event
 * (e.g. `event: model.text.delta`) is delivered to one handler. Returns an
 * AbortController; call .abort() to disconnect.
 */
export function streamRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  opts: { afterSeq?: number; onError?: (err: unknown) => void; onClose?: () => void } = {}
): AbortController {
  const ctrl = new AbortController();
  const url = `${BASE}/runs/${encodeURIComponent(runId)}/events${
    opts.afterSeq ? `?after_seq=${opts.afterSeq}` : ""
  }`;
  (async () => {
    try {
      const res = await fetch(url, {
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
