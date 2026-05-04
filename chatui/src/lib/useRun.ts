import { useCallback, useEffect, useRef, useState } from "react";
import { cancelRun, decideApproval, fetchArtifactText, listSessions, startRun, streamRunEvents } from "./api";
import type { ApprovalDecision, RunEvent, SessionSummary } from "./api";

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
  href?: string;
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

const isUserVisible = (event: RunEvent): boolean =>
  event.visibility === "public" || event.visibility === "user";

const toolStepId = (event: RunEvent): string =>
  String(event.data?.tool_call_id ?? event.item_id ?? event.id);

const modelTextKey = (event: RunEvent): string =>
  String(event.data?.model_call_id ?? event.item_id ?? event.id);

const modelTextStepId = (modelCallId: string): string => `model-text-${modelCallId}`;

const lastPendingModelTextKey = (pending: Record<string, string>): string => {
  const keys = Object.keys(pending);
  return keys.length ? keys[keys.length - 1] : "";
};

const artifactHref = (runId: string, path: string): string =>
  `/api/runs/${encodeURIComponent(runId)}/artifacts/${path
    .split("/")
    .map(encodeURIComponent)
    .join("/")}`;

const finalAnswerText = (text: string): string =>
  text.replace(/^# Final output\n\n/, "").trimEnd();

const stripAnswerSuffix = (answer: string, suffix: string): string =>
  suffix && answer.endsWith(suffix) ? answer.slice(0, -suffix.length).trimEnd() : answer;

const makeSessionId = (): string => {
  const id =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "")
      : `${Date.now()}${Math.random().toString(16).slice(2)}`;
  return `sess_${id}`;
};

export function useRun() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "thinking" | "streaming">("idle");
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<AbortController | null>(null);
  const activeTurnIdRef = useRef<string | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const pendingModelTextRef = useRef<Record<string, string>>({});
  const lastSeqRef = useRef(0);

  const stopStream = useCallback(() => {
    streamRef.current?.abort();
    streamRef.current = null;
  }, []);

  useEffect(() => () => stopStream(), [stopStream]);

  const refreshSessions = useCallback(() => {
    void listSessions()
      .then(setSessions)
      .catch(() => undefined);
  }, []);

  useEffect(() => refreshSessions(), [refreshSessions]);

  const updateTurn = useCallback((id: string, fn: (t: Turn) => Turn) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));
  }, []);

  const handleEvent = useCallback(
    (turnId: string) => (event: RunEvent) => {
      lastSeqRef.current = Math.max(lastSeqRef.current, event.seq ?? 0);
      const data = event.data ?? {};
      switch (event.type) {
        case "run.started": {
          updateTurn(turnId, (t) => ({ ...t, phase: "thinking" }));
          setPhase("thinking");
          break;
        }
        case "model.reasoning.delta": {
          if (!isUserVisible(event)) break;
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
          const id = toolStepId(event);
          const eventModelCallId = typeof data.model_call_id === "string" ? data.model_call_id : "";
          const pendingKey = eventModelCallId || lastPendingModelTextKey(pendingModelTextRef.current);
          const pendingText = pendingKey ? pendingModelTextRef.current[pendingKey] : "";
          if (pendingKey) {
            delete pendingModelTextRef.current[pendingKey];
          }
          const step: ReasoningStep = {
            kind: "tool",
            id,
            tool,
            label: summary ? `${tool} — ${summary}` : tool,
            argsSummary: summary,
            status: "running",
          };
          updateTurn(turnId, (t) => {
            const nextAnswer = pendingText ? stripAnswerSuffix(t.answer, pendingText) : t.answer;
            const textStepId = pendingKey ? modelTextStepId(pendingKey) : `model-text-${event.id}`;
            const seededSteps =
              pendingText && !t.steps.some((s) => s.kind === "text" && s.id === textStepId)
                ? [
                    ...t.steps,
                    { kind: "text" as const, id: textStepId, text: pendingText },
                  ]
                : t.steps;
            const idx = seededSteps.findIndex((s) => s.kind === "tool" && s.id === id);
            if (idx >= 0) {
              const next = [...seededSteps];
              next[idx] = { ...step, status: (next[idx] as Extract<ReasoningStep, { kind: "tool" }>).status };
              return { ...t, answer: nextAnswer, steps: next };
            }
            return { ...t, answer: nextAnswer, steps: [...seededSteps, step] };
          });
          break;
        }
        case "tool.execution.started": {
          const id = toolStepId(event);
          const tool = String(data.tool ?? "tool");
          updateTurn(turnId, (t) => ({
            ...t,
            steps: t.steps.some((s) => s.kind === "tool" && s.id === id)
              ? t.steps.map((s) =>
                  s.kind === "tool" && s.id === id ? { ...s, status: "running" as ToolStatus } : s
                )
              : [
                  ...t.steps,
                  { kind: "tool", id, tool, label: tool, argsSummary: "", status: "running" },
                ],
          }));
          break;
        }
        case "tool.execution.completed":
        case "tool.execution.failed":
        case "tool.execution.cancelled":
        case "tool.execution.blocked": {
          const id = toolStepId(event);
          const tool = String(data.tool ?? "tool");
          const status: ToolStatus =
            event.type === "tool.execution.completed"
              ? "done"
              : event.type === "tool.execution.failed"
                ? "failed"
                : event.type === "tool.execution.cancelled"
                  ? "cancelled"
                  : "blocked";
          updateTurn(turnId, (t) => {
            const output = typeof data.output === "string" ? data.output : undefined;
            if (!t.steps.some((s) => s.kind === "tool" && s.id === id)) {
              return {
                ...t,
                steps: [
                  ...t.steps,
                  { kind: "tool", id, tool, label: tool, argsSummary: "", status, output },
                ],
              };
            }
            return {
              ...t,
              steps: t.steps.map((s) =>
                s.kind === "tool" && s.id === id ? { ...s, status, output: output ?? s.output } : s
              ),
            };
          });
          break;
        }
        case "model.text.delta": {
          const delta = String(data.delta ?? "");
          if (!delta) break;
          const key = modelTextKey(event);
          pendingModelTextRef.current[key] = `${pendingModelTextRef.current[key] ?? ""}${delta}`;
          updateTurn(turnId, (t) => {
            setPhase("streaming");
            return { ...t, answer: t.answer + delta, phase: "streaming" };
          });
          break;
        }
        case "model.call.completed": {
          const modelCallId = typeof data.model_call_id === "string" ? data.model_call_id : "";
          const toolCallCount = Number(data.tool_call_count ?? 0);
          if (modelCallId && toolCallCount === 0) {
            delete pendingModelTextRef.current[modelCallId];
          }
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
          const outputPath = typeof data.output_path === "string" ? data.output_path : "";
          if (outputPath) {
            void fetchArtifactText(event.run_id, outputPath)
              .then((artifactText) => {
                if (!artifactText) return;
                const finalText = finalAnswerText(artifactText);
                pendingModelTextRef.current = {};
                updateTurn(turnId, (t) => ({
                  ...t,
                  answer: finalText || t.answer,
                  phase: t.phase === "thinking" ? "streaming" : t.phase,
                }));
              })
              .catch(() => undefined);
          }
          break;
        }
        case "approval.requested": {
          const command = typeof data.command === "string" ? data.command : "";
          const argsPreview = typeof data.args_preview === "string" ? data.args_preview : "";
          const risk = typeof data.risk === "string" ? data.risk : "";
          setApproval({
            runId: event.run_id,
            approvalId: String(data.approval_id ?? ""),
            kind: String(data.tool_name ?? data.tool ?? data.action_kind ?? "approval"),
            title: command || argsPreview || "Approval needed",
            detail: [risk ? `risk: ${risk}` : "", argsPreview && argsPreview !== command ? argsPreview : ""]
              .filter(Boolean)
              .join("\n"),
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
          const path = String(data.path ?? data.output_path ?? data.name ?? "");
          const id = path || String(event.item_id ?? event.id);
          const title =
            String(data.title ?? path ?? data.name ?? "Artifact") || "Artifact";
          const tool = String(data.tool ?? "");
          const kind: Artifact["kind"] = toolKindFor(tool);
          const href = path ? artifactHref(event.run_id, path) : undefined;
          setArtifacts((prev) => {
            const exists = prev.find((a) => a.id === id);
            if (exists) {
              return prev.map((a) => (a.id === id ? { ...a, state: "updated", title, href } : a));
            }
            return [{ id, title, kind, state: "creating", time: "now", href }, ...prev];
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
          refreshSessions();
          break;
        }
        case "run.failed": {
          updateTurn(turnId, (t) => ({ ...t, phase: "failed" }));
          setPhase("idle");
          refreshSessions();
          break;
        }
        case "run.cancelled": {
          updateTurn(turnId, (t) => ({ ...t, phase: "cancelled" }));
          setPhase("idle");
          refreshSessions();
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
      pendingModelTextRef.current = {};
      lastSeqRef.current = 0;
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
        if (!sessionIdRef.current) {
          sessionIdRef.current = makeSessionId();
        }
        const { run_id, session_id } = await startRun(trimmed, {
          approval_mode: mode,
          session_id: sessionIdRef.current,
          turn_id: turnId,
        });
        if (session_id) {
          sessionIdRef.current = session_id;
          setActiveSessionId(session_id);
          setSessions((prev) => upsertLocalSession(prev, session_id, trimmed));
        }
        activeRunIdRef.current = run_id;
        updateTurn(turnId, (t) => ({ ...t, runId: run_id }));
        streamRef.current?.abort();
        streamRef.current = streamRunEvents(run_id, handleEvent(turnId), {
          afterSeq: lastSeqRef.current,
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

  const newSession = useCallback(() => {
    stopStream();
    activeTurnIdRef.current = null;
    activeRunIdRef.current = null;
    sessionIdRef.current = null;
    pendingModelTextRef.current = {};
    lastSeqRef.current = 0;
    setActiveSessionId(null);
    setTurns([]);
    setArtifacts([]);
    setApproval(null);
    setError(null);
    setPhase("idle");
    refreshSessions();
  }, [refreshSessions, stopStream]);

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
    sessions,
    activeSessionId,
    error,
    send,
    stop,
    newSession,
    respondToApproval,
  };
}

function upsertLocalSession(sessions: SessionSummary[], sessionId: string, title: string): SessionSummary[] {
  const now = new Date().toISOString();
  const existing = sessions.find((session) => session.session_id === sessionId);
  if (existing) {
    return [
      { ...existing, title: existing.title || title, updated_at: now },
      ...sessions.filter((session) => session.session_id !== sessionId),
    ];
  }
  return [
    {
      session_id: sessionId,
      title,
      status: "open",
      active_turn_id: null,
      created_at: now,
      updated_at: now,
      workspace: "",
      turn_count: 0,
    },
    ...sessions,
  ];
}
