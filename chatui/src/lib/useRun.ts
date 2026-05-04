import { useCallback, useEffect, useRef, useState } from "react";
import { cancelRun, decideApproval, startRun, streamRunEvents } from "./api";
import type { ApprovalDecision, RunEvent } from "./api";

export type ToolStatus = "running" | "done" | "failed" | "blocked" | "cancelled";

export type ReasoningStep =
  | { kind: "text"; id: string; text: string }
  | {
      kind: "tool";
      id: string;
      tool: string;
      label: string;
      argsSummary: string;
      status: ToolStatus;
      output?: string;
    };

export type TurnPhase = "thinking" | "streaming" | "done" | "failed" | "cancelled";

export type Turn = {
  id: string;
  runId: string | null;
  user: string;
  steps: ReasoningStep[];
  answer: string;
  startedAt: number;
  durationSec: number;
  phase: TurnPhase;
};

export type Approval = {
  runId: string;
  approvalId: string;
  kind: string;
  title: string;
  detail: string;
};

export type Artifact = {
  id: string;
  title: string;
  kind: "doc" | "chart" | "image" | "code" | "file";
  state: "creating" | "updated" | "done";
  time: string;
};

const summarizeArgs = (args: any): string => {
  if (!args || typeof args !== "object") return "";
  if (typeof args.cmd === "string") return args.cmd;
  if (typeof args.patch === "string") return "patch";
  try {
    const s = JSON.stringify(args);
    return s.length > 80 ? s.slice(0, 80) + "…" : s;
  } catch {
    return "";
  }
};

const toolIconFor = (name: string): string => {
  switch (name) {
    case "shell":
    case "bash":
      return "code";
    case "apply_patch":
    case "edit":
      return "doc";
    case "read_file":
    case "list_files":
      return "doc";
    case "search_repo":
    case "grep":
      return "search";
    default:
      return "search";
  }
};

const toolKindFor = (name: string): Artifact["kind"] => {
  switch (name) {
    case "apply_patch":
    case "edit":
    case "read_file":
      return "file";
    default:
      return "file";
  }
};

export function useRun() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [phase, setPhase] = useState<"idle" | "thinking" | "streaming">("idle");
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<AbortController | null>(null);
  const activeTurnIdRef = useRef<string | null>(null);
  const activeRunIdRef = useRef<string | null>(null);

  const stopStream = useCallback(() => {
    streamRef.current?.abort();
    streamRef.current = null;
  }, []);

  useEffect(() => () => stopStream(), [stopStream]);

  const updateTurn = useCallback((id: string, fn: (t: Turn) => Turn) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));
  }, []);

  const handleEvent = useCallback(
    (turnId: string) => (event: RunEvent) => {
      const data = event.data ?? {};
      switch (event.type) {
        case "run.started": {
          updateTurn(turnId, (t) => ({ ...t, phase: "thinking" }));
          setPhase("thinking");
          break;
        }
        case "model.reasoning.delta": {
          const delta = String(data.delta ?? "");
          if (!delta) break;
          const reasoningId = event.item_id ?? event.id;
          updateTurn(turnId, (t) => {
            const idx = t.steps.findIndex((s) => s.kind === "text" && s.id === reasoningId);
            if (idx >= 0) {
              const existing = t.steps[idx] as Extract<ReasoningStep, { kind: "text" }>;
              const next = [...t.steps];
              next[idx] = { ...existing, text: existing.text + delta };
              return { ...t, steps: next };
            }
            return {
              ...t,
              steps: [...t.steps, { kind: "text", id: reasoningId, text: delta }],
            };
          });
          break;
        }
        case "model.reasoning.completed": {
          const reasoningId = event.item_id ?? "";
          const finalText = typeof data.reason === "string" ? data.reason : "";
          if (!finalText) break;
          updateTurn(turnId, (t) => {
            const idx = t.steps.findIndex((s) => s.kind === "text" && s.id === reasoningId);
            if (idx >= 0) return t;
            return {
              ...t,
              steps: [...t.steps, { kind: "text", id: reasoningId || event.id, text: finalText }],
            };
          });
          break;
        }
        case "model.tool_call.assembly.completed": {
          const tool = String(data.tool ?? "tool");
          const args = data.args ?? {};
          const summary = summarizeArgs(args);
          const step: ReasoningStep = {
            kind: "tool",
            id: event.item_id ?? event.id,
            tool,
            label: summary ? `${tool} — ${summary}` : tool,
            argsSummary: summary,
            status: "running",
          };
          updateTurn(turnId, (t) => ({ ...t, steps: [...t.steps, step] }));
          break;
        }
        case "tool.execution.started": {
          const id = event.item_id ?? "";
          updateTurn(turnId, (t) => ({
            ...t,
            steps: t.steps.map((s) =>
              s.kind === "tool" && s.id === id ? { ...s, status: "running" as ToolStatus } : s
            ),
          }));
          break;
        }
        case "tool.execution.completed":
        case "tool.execution.failed":
        case "tool.execution.cancelled":
        case "tool.execution.blocked": {
          const id = event.item_id ?? "";
          const status: ToolStatus =
            event.type === "tool.execution.completed"
              ? "done"
              : event.type === "tool.execution.failed"
                ? "failed"
                : event.type === "tool.execution.cancelled"
                  ? "cancelled"
                  : "blocked";
          updateTurn(turnId, (t) => ({
            ...t,
            steps: t.steps.map((s) =>
              s.kind === "tool" && s.id === id
                ? { ...s, status, output: typeof data.output === "string" ? data.output : s.output }
                : s
            ),
          }));
          break;
        }
        case "model.text.delta": {
          const delta = String(data.delta ?? "");
          if (!delta) break;
          updateTurn(turnId, (t) => ({ ...t, answer: t.answer + delta, phase: "streaming" }));
          setPhase("streaming");
          break;
        }
        case "model.message.completed": {
          const text = data.text;
          if (typeof text === "string" && text) {
            updateTurn(turnId, (t) => ({
              ...t,
              answer: t.answer || text,
              phase: "streaming",
            }));
          }
          break;
        }
        case "approval.requested": {
          setApproval({
            runId: event.run_id,
            approvalId: String(data.approval_id ?? ""),
            kind: String(data.tool ?? data.kind ?? "approval"),
            title: String(data.summary ?? data.title ?? "Approval needed"),
            detail: String(data.detail ?? data.preview ?? ""),
          });
          break;
        }
        case "approval.resolved":
        case "approval.expired": {
          setApproval((prev) =>
            prev && prev.approvalId === String(data.approval_id ?? "") ? null : prev
          );
          break;
        }
        case "artifact.created":
        case "artifact.materialized": {
          const id = String(event.item_id ?? event.id);
          const title =
            String(data.title ?? data.path ?? data.name ?? "Artifact") || "Artifact";
          const tool = String(data.tool ?? "");
          const kind: Artifact["kind"] = toolKindFor(tool);
          setArtifacts((prev) => {
            const exists = prev.find((a) => a.id === id);
            if (exists) {
              return prev.map((a) => (a.id === id ? { ...a, state: "updated", title } : a));
            }
            return [{ id, title, kind, state: "creating", time: "now" }, ...prev];
          });
          break;
        }
        case "run.completed": {
          updateTurn(turnId, (t) => ({
            ...t,
            phase: "done",
            durationSec: Math.max(1, Math.round((Date.now() - t.startedAt) / 1000)),
          }));
          setPhase("idle");
          setArtifacts((prev) => prev.map((a) => ({ ...a, state: "done" })));
          break;
        }
        case "run.failed": {
          updateTurn(turnId, (t) => ({ ...t, phase: "failed" }));
          setPhase("idle");
          break;
        }
        case "run.cancelled": {
          updateTurn(turnId, (t) => ({ ...t, phase: "cancelled" }));
          setPhase("idle");
          break;
        }
      }
    },
    [updateTurn]
  );

  const send = useCallback(
    async (text: string, mode: "yolo" | "on-request" = "yolo") => {
      if (phase !== "idle") return;
      const trimmed = text.trim();
      if (!trimmed) return;

      const turnId = `turn_${Date.now()}`;
      activeTurnIdRef.current = turnId;
      setError(null);
      const draft: Turn = {
        id: turnId,
        runId: null,
        user: trimmed,
        steps: [],
        answer: "",
        startedAt: Date.now(),
        durationSec: 0,
        phase: "thinking",
      };
      setTurns((prev) => [...prev, draft]);
      setPhase("thinking");

      try {
        const { run_id } = await startRun(trimmed, { approval_mode: mode });
        activeRunIdRef.current = run_id;
        updateTurn(turnId, (t) => ({ ...t, runId: run_id }));
        streamRef.current?.abort();
        streamRef.current = streamRunEvents(run_id, handleEvent(turnId), {
          onError: (e) => setError(e instanceof Error ? e.message : String(e)),
          onClose: () => {
            if (activeTurnIdRef.current === turnId) {
              activeTurnIdRef.current = null;
              activeRunIdRef.current = null;
              setPhase("idle");
            }
          },
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        updateTurn(turnId, (t) => ({ ...t, phase: "failed" }));
        setPhase("idle");
      }
    },
    [phase, handleEvent, updateTurn]
  );

  const stop = useCallback(async () => {
    const runId = activeRunIdRef.current;
    if (runId) await cancelRun(runId);
    stopStream();
    const turnId = activeTurnIdRef.current;
    if (turnId) updateTurn(turnId, (t) => ({ ...t, phase: "cancelled" }));
    setPhase("idle");
    activeTurnIdRef.current = null;
    activeRunIdRef.current = null;
  }, [stopStream, updateTurn]);

  const respondToApproval = useCallback(
    async (decision: ApprovalDecision) => {
      if (!approval) return;
      await decideApproval(approval.runId, approval.approvalId, decision);
      setApproval(null);
    },
    [approval]
  );

  return {
    turns,
    phase,
    approval,
    artifacts,
    error,
    send,
    stop,
    respondToApproval,
  };
}
