import { useCallback, useEffect, useRef, useState } from "react";
import { tinyagent } from "./api";
import type { ApprovalDecision, ConversationSummary, RunEvent, WorkspaceSummary } from "./api";

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

const modelReasoningStepId = (modelCallId: string): string => `model-reasoning-${modelCallId}`;

const lastPendingModelTextKey = (pending: Record<string, string>): string => {
  const keys = Object.keys(pending);
  return keys.length ? keys[keys.length - 1] : "";
};

const artifactHref = (workspaceId: string, runId: string, path: string): string =>
  `/api/runs/${encodeURIComponent(runId)}/artifacts/${path
    .split("/")
    .map(encodeURIComponent)
    .join("/")}?workspace_id=${encodeURIComponent(workspaceId)}`;

const finalAnswerText = (text: string): string =>
  text.replace(/^# Final output\n\n/, "").trimEnd();

const stripAnswerSuffix = (answer: string, suffix: string): string =>
  suffix && answer.endsWith(suffix) ? answer.slice(0, -suffix.length).trimEnd() : answer;

const makeConversationId = (): string => {
  const id =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "")
      : `${Date.now()}${Math.random().toString(16).slice(2)}`;
  return `conv_${id}`;
};

export function useRun() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [workspaces, setWorkspaces] = useState<WorkspaceSummary[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [phase, setPhase] = useState<"idle" | "thinking" | "streaming">("idle");
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<AbortController | null>(null);
  const activeTurnIdRef = useRef<string | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const conversationIdRef = useRef<string | null>(null);
  const workspaceIdRef = useRef<string | null>(null);
  const pendingModelTextRef = useRef<Record<string, string>>({});
  const replayingRef = useRef(false);
  const lastSeqRef = useRef(0);

  const stopStream = useCallback(() => {
    streamRef.current?.abort();
    streamRef.current = null;
  }, []);

  useEffect(() => () => stopStream(), [stopStream]);

  const refreshWorkspaces = useCallback(() => {
    void tinyagent.listWorkspaces()
      .then((rows) => {
        setWorkspaces(rows);
        setActiveWorkspaceId((current) => {
          const next = current && rows.some((workspace) => workspace.workspace_id === current) ? current : rows[0]?.workspace_id ?? null;
          workspaceIdRef.current = next;
          return next;
        });
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => refreshWorkspaces(), [refreshWorkspaces]);

  const addWorkspace = useCallback(async (path: string) => {
    const workspace = await tinyagent.registerWorkspace(path);
    setWorkspaces((rows) => [workspace, ...rows.filter((row) => row.workspace_id !== workspace.workspace_id)]);
    workspaceIdRef.current = workspace.workspace_id;
    setActiveWorkspaceId(workspace.workspace_id);
    return workspace;
  }, []);

  const refreshConversations = useCallback(() => {
    const workspaceId = workspaceIdRef.current;
    if (!workspaceId) {
      setConversations([]);
      return;
    }
    void tinyagent.listConversations(workspaceId)
      .then(setConversations)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    workspaceIdRef.current = activeWorkspaceId;
    refreshConversations();
  }, [activeWorkspaceId, refreshConversations]);

  const updateTurn = useCallback((id: string, fn: (t: Turn) => Turn) => {
    setTurns((prev) => prev.map((t) => (t.id === id ? fn(t) : t)));
  }, []);

  const clearActiveRun = useCallback((turnId: string) => {
    if (activeTurnIdRef.current === turnId) {
      activeTurnIdRef.current = null;
      activeRunIdRef.current = null;
    }
  }, []);

  const handleEvent = useCallback(
    (turnId: string) => (event: RunEvent) => {
      lastSeqRef.current = Math.max(lastSeqRef.current, event.seq ?? 0);
      const data = event.data ?? {};
      switch (event.type) {
        case "run.started": {
          updateTurn(turnId, (t) => ({ ...t, phase: "thinking" }));
          if (!replayingRef.current) setPhase("thinking");
          break;
        }
        case "model.reasoning.delta": {
          if (!isUserVisible(event)) break;
          const delta = String(data.delta ?? "");
          if (!delta) break;
          const modelCallId = typeof data.model_call_id === "string" ? data.model_call_id : "";
          const reasoningId = modelCallId ? modelReasoningStepId(modelCallId) : event.item_id ?? event.id;
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
          const modelCallId = typeof data.model_call_id === "string" ? data.model_call_id : "";
          const reasoningId = modelCallId ? modelReasoningStepId(modelCallId) : event.item_id ?? "";
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
          if (!replayingRef.current) setPhase("streaming");
          updateTurn(turnId, (t) => ({ ...t, answer: t.answer + delta, phase: "streaming" }));
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
            const workspaceId = workspaceIdRef.current;
            if (!workspaceId) break;
            void tinyagent.fetchArtifactText(workspaceId, event.run_id, outputPath)
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
          const workspaceId = workspaceIdRef.current;
          const href = path && workspaceId ? artifactHref(workspaceId, event.run_id, path) : undefined;
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
          const durationSeconds = Number(data.duration_seconds);
          updateTurn(turnId, (t) => ({
            ...t,
            phase: "done",
            durationSec: Number.isFinite(durationSeconds) && durationSeconds > 0
              ? Math.max(1, Math.round(durationSeconds))
              : Math.max(1, Math.round((Date.now() - t.startedAt) / 1000)),
          }));
          clearActiveRun(turnId);
          setPhase("idle");
          setArtifacts((prev) => prev.map((a) => ({ ...a, state: "done" })));
          refreshConversations();
          break;
        }
        case "run.failed": {
          updateTurn(turnId, (t) => ({ ...t, phase: "failed" }));
          clearActiveRun(turnId);
          setPhase("idle");
          refreshConversations();
          break;
        }
        case "run.cancelled": {
          updateTurn(turnId, (t) => ({ ...t, phase: "cancelled" }));
          clearActiveRun(turnId);
          setPhase("idle");
          refreshConversations();
          break;
        }
      }
    },
    [clearActiveRun, refreshConversations, updateTurn]
  );

  const send = useCallback(
    async (text: string, mode: "yolo" | "on-request" = "yolo") => {
      if (phase !== "idle") return;
      const trimmed = text.trim();
      if (!trimmed) return;
      const workspaceId = workspaceIdRef.current;
      if (!workspaceId) {
        setError("Select a workspace before starting a conversation.");
        return;
      }

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
        if (!conversationIdRef.current) {
          conversationIdRef.current = makeConversationId();
        }
        const { run_id, conversation_id } = await tinyagent.startConversationTurn(workspaceId, conversationIdRef.current, trimmed, {
          approval_mode: mode,
          turn_id: turnId,
        });
        if (conversation_id) {
          conversationIdRef.current = conversation_id;
          setActiveConversationId(conversation_id);
          setConversations((prev) => upsertLocalConversation(prev, conversation_id, trimmed));
        }
        activeRunIdRef.current = run_id;
        updateTurn(turnId, (t) => ({ ...t, runId: run_id }));
        streamRef.current?.abort();
        streamRef.current = tinyagent.streamRunEvents(workspaceId, run_id, handleEvent(turnId), {
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

  const newConversation = useCallback(() => {
    stopStream();
    activeTurnIdRef.current = null;
    activeRunIdRef.current = null;
    conversationIdRef.current = null;
    pendingModelTextRef.current = {};
    lastSeqRef.current = 0;
    setActiveConversationId(null);
    setTurns([]);
    setArtifacts([]);
    setApproval(null);
    setError(null);
    setPhase("idle");
    refreshConversations();
  }, [refreshConversations, stopStream]);

  const selectWorkspace = useCallback(
    (workspaceId: string) => {
      if (phase !== "idle") return;
      workspaceIdRef.current = workspaceId;
      setActiveWorkspaceId(workspaceId);
      newConversation();
    },
    [newConversation, phase]
  );

  const selectConversation = useCallback(
    async (conversationId: string) => {
      stopStream();
      const conversation = conversations.find((item) => item.conversation_id === conversationId);
      conversationIdRef.current = conversationId;
      activeTurnIdRef.current = null;
      activeRunIdRef.current = null;
      pendingModelTextRef.current = {};
      lastSeqRef.current = 0;
      setActiveConversationId(conversationId);
      setTurns([]);
      setArtifacts([]);
      setApproval(null);
      setError(null);
      setPhase("idle");
      if (!conversation?.last_run_id) return;

      try {
        const workspaceId = workspaceIdRef.current;
        if (!workspaceId) return;
        const events = await tinyagent.fetchRunEvents(workspaceId, conversation.last_run_id);
        const started = events.find((event) => event.type === "run.started");
        const turnId =
          started?.turn_id ||
          conversation.active_turn_id ||
          events.find((event) => event.turn_id)?.turn_id ||
          `loaded_${conversation.last_run_id}`;
        const task = String(started?.data?.task || conversation.title || "New conversation");
        const startedAt = started?.time ? Date.parse(started.time) : NaN;
        setTurns([
          {
            id: turnId,
            runId: conversation.last_run_id,
            user: task,
            steps: [],
            answer: "",
            startedAt: Number.isNaN(startedAt) ? Date.now() : startedAt,
            durationSec: 0,
            phase: "thinking",
          },
        ]);
        const applyEvent = handleEvent(turnId);
        replayingRef.current = true;
        try {
          for (const event of events) {
            lastSeqRef.current = Math.max(lastSeqRef.current, event.seq ?? 0);
            applyEvent(event);
          }
          const sawTerminalEvent = events.some((event) =>
            ["run.completed", "run.failed", "run.cancelled"].includes(event.type)
          );
          if (!sawTerminalEvent) {
            const fallbackPhase: TurnPhase =
              conversation.last_turn_status === "cancelled"
                ? "cancelled"
                : conversation.last_turn_status === "failed"
                  ? "failed"
                  : "done";
            updateTurn(turnId, (t) => ({
              ...t,
              phase: fallbackPhase,
            }));
          }
        } finally {
          replayingRef.current = false;
        }
        setPhase("idle");
      } catch (e) {
        replayingRef.current = false;
        setError(e instanceof Error ? e.message : String(e));
        setPhase("idle");
      }
    },
    [handleEvent, conversations, stopStream, updateTurn]
  );

  const stop = useCallback(async () => {
    const runId = activeRunIdRef.current;
    const workspaceId = workspaceIdRef.current;
    if (runId && workspaceId) await tinyagent.cancelRun(workspaceId, runId);
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
      const workspaceId = workspaceIdRef.current;
      if (!workspaceId) return;
      await tinyagent.decideApproval(workspaceId, approval.runId, approval.approvalId, decision);
      setApproval(null);
    },
    [approval]
  );

  return {
    turns,
    phase,
    approval,
    artifacts,
    workspaces,
    activeWorkspaceId,
    conversations,
    activeConversationId,
    error,
    send,
    stop,
    addWorkspace,
    refreshWorkspaces,
    selectWorkspace,
    newConversation,
    selectConversation,
    respondToApproval,
  };
}

function upsertLocalConversation(conversations: ConversationSummary[], conversationId: string, title: string): ConversationSummary[] {
  const now = new Date().toISOString();
  const existing = conversations.find((conversation) => conversation.conversation_id === conversationId);
  if (existing) {
    return [
      { ...existing, title: existing.title || title, updated_at: now },
      ...conversations.filter((conversation) => conversation.conversation_id !== conversationId),
    ];
  }
  return [
    {
      conversation_id: conversationId,
      title,
      status: "open",
      active_turn_id: null,
      created_at: now,
      updated_at: now,
      workspace: "",
      turn_count: 0,
    },
    ...conversations,
  ];
}
