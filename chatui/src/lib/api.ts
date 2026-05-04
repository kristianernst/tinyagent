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
};

export type ApprovalDecision = "approved" | "denied" | "cancelled" | "expired";

const BASE = "/api";

export async function startRun(
  task: string,
  opts: { run_id?: string; approval_mode?: "yolo" | "on-request" | "never" } = {}
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
  let dataLine: string | null = null;
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("data:")) {
      dataLine = line.slice(5).trimStart();
    }
  }
  if (!dataLine) return null;
  try {
    return JSON.parse(dataLine) as RunEvent;
  } catch {
    return null;
  }
}
