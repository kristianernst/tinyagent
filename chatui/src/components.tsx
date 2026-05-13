import { useEffect, useRef, useState } from "react";
import type { ReactNode, KeyboardEvent } from "react";
import {
  IconArrowUp,
  IconAsk,
  IconAuto,
  IconChart,
  IconChev,
  IconCode,
  IconDb,
  IconDoc,
  IconMic,
  IconPlus,
  IconSearch,
  IconStop,
  IconTerminal,
  IconWeb,
  IconYolo,
} from "./icons";
import { AgentOrb } from "./AgentOrb";
import { Markdown } from "./Markdown";
import type { Approval, ReasoningStep, Turn } from "./lib/useRun";

// ---------------- Smooth height collapsible ----------------
export function Collapsible({
  open,
  children,
  duration = 380,
}: {
  open: boolean;
  children: ReactNode;
  duration?: number;
}) {
  return (
    <div
      className="collapsible"
      data-open={open ? "true" : "false"}
      style={{ ["--dur" as any]: `${duration}ms` }}
    >
      <div className="collapsible-inner">{children}</div>
    </div>
  );
}

// ---------------- Tool pill ----------------
const TOOL_ICONS: Record<string, (p: any) => any> = {
  search: IconSearch,
  db: IconDb,
  web: IconWeb,
  doc: IconDoc,
  code: IconCode,
  chart: IconChart,
  shell: IconTerminal,
  apply_patch: IconDoc,
  read_file: IconDoc,
  list_files: IconDoc,
  search_repo: IconSearch,
};

export function ToolPill({
  tool,
  label,
  status = "done",
  expandable = true,
  children,
}: {
  tool: string;
  label: string;
  status?: "running" | "done" | "failed" | "blocked" | "cancelled";
  expandable?: boolean;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const Ico = TOOL_ICONS[tool] ?? TOOL_ICONS.search;

  const onKey = (e: KeyboardEvent) => {
    if (!expandable) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setOpen((o) => !o);
    }
  };

  return (
    <div
      className={`tool-pill-wrap ${expandable ? "is-expandable" : ""} ${
        open ? "is-open is-locked" : ""
      } ${status === "running" ? "is-running" : ""}`}
    >
      <button
        type="button"
        className="tool-pill"
        onClick={() => expandable && setOpen((o) => !o)}
        onKeyDown={onKey}
        tabIndex={expandable ? 0 : -1}
        aria-expanded={expandable ? open : undefined}
      >
        <Ico className="ico" />
        <span className="label">{label}</span>
        {expandable && <IconChev className="chev" />}
        {status === "running" && <span className="pulse" />}
      </button>
      {expandable && (
        <Collapsible open={open} duration={460}>
          <div className="tool-content">{children}</div>
        </Collapsible>
      )}
    </div>
  );
}

// ---------------- Reasoning ----------------
export function Reasoning({
  steps,
  durationSec,
  status,
  seed,
  defaultOpen = true,
}: {
  steps: ReasoningStep[];
  durationSec: number;
  status: "thinking" | "done";
  seed: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const isThinking = status === "thinking";

  return (
    <div className={`reasoning ${open ? "open" : ""} fade-up`}>
      <div
        className={`reasoning-header ${isThinking ? "thinking" : "done"}`}
        onClick={() => setOpen((o) => !o)}
      >
        <AgentOrb seed={seed} running={isThinking} size={16} />
        <span className="label">
          {isThinking ? "Running…" : `Worked for ${durationSec || 1}s`}
        </span>
        <IconChev className="chev" />
      </div>
      <Collapsible open={open} duration={500}>
        <div className="reasoning-content">
          {steps.map((step, i) => (
            <Step key={step.id + i} step={step} active={isThinking && i === steps.length - 1} index={i} />
          ))}
        </div>
      </Collapsible>
    </div>
  );
}

function Step({ step, active, index }: { step: ReasoningStep; active: boolean; index: number }) {
  const delay = `${index * 0.08}s`;
  if (step.kind === "text") {
    return (
      <div className={`rstep fade-up ${active ? "active" : ""}`} style={{ animationDelay: delay }}>
        <Markdown text={step.text} compact />
      </div>
    );
  }
  if (step.kind === "tool") {
    return (
      <div className="fade-up rstep-tool" style={{ animationDelay: delay }}>
        <ToolPill tool={step.tool} label={step.label} status={step.status}>
          {step.output ? <ToolOutput text={step.output} /> : null}
        </ToolPill>
      </div>
    );
  }
  return null;
}

export function AnswerText({ text, streaming }: { text: string; streaming: boolean }) {
  return (
    <div className="answer-wrap">
      <Markdown text={text} />
      {streaming && <span className="stream-cursor" />}
    </div>
  );
}

function ToolOutput({ text }: { text: string }) {
  if (looksLikeDiff(text)) return <DiffPreview diff={text} />;
  return <pre className="codeblock">{text}</pre>;
}

function looksLikeDiff(text: string) {
  return /^diff --git /m.test(text) || /^@@ /m.test(text) || /^--- .+\n\+\+\+ /m.test(text);
}

function DiffPreview({ diff }: { diff: string }) {
  const [expanded, setExpanded] = useState(false);
  const lines = diff.split("\n");
  const visible = expanded ? lines : lines.slice(0, 80);
  return (
    <div className="toolPanel diffPanel">
      <pre className="diffBody">
        {visible.map((line, index) => (
          <div key={index} className={`diffLine ${diffLineClass(line)}`}>{line || " "}</div>
        ))}
      </pre>
      {lines.length > 80 && (
        <button className="diffToggle" onClick={() => setExpanded((value) => !value)}>
          {expanded ? "Show less" : `Show all ${lines.length} lines`}
        </button>
      )}
    </div>
  );
}

export function diffLineClass(line: string) {
  if (line.startsWith("+++") || line.startsWith("---")) return "diffMeta";
  if (line.startsWith("@@")) return "diffHunk";
  if (line.startsWith("+")) return "diffAdd";
  if (line.startsWith("-")) return "diffDel";
  return "diffCtx";
}

// ---------------- Turn ----------------
export function TurnView({ turn }: { turn: Turn }) {
  const reasoningStatus: "thinking" | "done" =
    turn.phase === "thinking" || (turn.phase === "streaming" && turn.steps.length > 0 && !turn.answer)
      ? "thinking"
      : "done";
  const isStreamingAnswer = turn.phase === "streaming";
  return (
    <>
      <div className="msg user fade-up">
        <div className="bubble">{turn.user}</div>
      </div>
      <div className="msg assistant">
        {turn.steps.length > 0 && (
          <Reasoning
            steps={turn.steps}
            durationSec={turn.durationSec}
            status={reasoningStatus}
            seed={turn.runId ?? turn.id}
          />
        )}
        {turn.answer && (
          <div className="fade-up">
            <AnswerText text={turn.answer} streaming={isStreamingAnswer} />
          </div>
        )}
        {turn.phase === "failed" && (
          <p style={{ color: "oklch(0.55 0.16 25)" }}>Run failed.</p>
        )}
        {turn.phase === "cancelled" && !turn.answer && (
          <p style={{ color: "var(--muted)" }}>Cancelled.</p>
        )}
      </div>
    </>
  );
}

// ---------------- Mode switch ----------------
const MODES = [
  { id: "yolo" as const, label: "yolo", Icon: IconYolo, desc: "YOLO — no approvals, fully autonomous." },
  { id: "auto" as const, label: "auto", Icon: IconAuto, desc: "Auto — handles routine tasks, asks before risky ones." },
  { id: "ask" as const, label: "ask", Icon: IconAsk, desc: "Ask — pauses for approval before every tool call." },
];
export type Mode = (typeof MODES)[number]["id"];

export function ModeSwitch({ value, onChange }: { value: Mode; onChange: (v: Mode) => void }) {
  const idx = Math.max(0, MODES.findIndex((m) => m.id === value));
  const active = MODES[idx] ?? MODES[1];
  const cycle = () => onChange(MODES[(idx + 1) % MODES.length].id);
  return (
    <button
      type="button"
      className={`comp-mode comp-mode-${active.id}`}
      onClick={cycle}
      title={active.desc + " (click to cycle)"}
      aria-label={`Permission mode: ${active.label}. Click to cycle.`}
    >
      <active.Icon size={11} strokeWidth={2.25} />
      <span className="comp-mode-label">{active.label}</span>
    </button>
  );
}

// ---------------- Composer ----------------
export function Composer({
  onSend,
  disabled,
  isStreaming,
  onStop,
  approval,
  onApprovalDecision,
  contextUsed = 0.0,
  contextTokens = "0k",
  contextMax = "128k",
  model = "tinyagent",
  reasoningEffort = "medium",
  mode,
  onModeChange,
}: {
  onSend: (v: string) => void;
  disabled: boolean;
  isStreaming: boolean;
  onStop: () => void;
  approval: Approval | null;
  onApprovalDecision: (decision: "approved" | "denied") => void;
  contextUsed?: number;
  contextTokens?: string;
  contextMax?: string;
  model?: string;
  reasoningEffort?: "low" | "medium" | "high";
  mode: Mode;
  onModeChange: (v: Mode) => void;
}) {
  const [val, setVal] = useState("");
  const [ctxHover, setCtxHover] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const t = ref.current;
    if (!t) return;
    t.style.height = "auto";
    t.style.height = Math.min(180, t.scrollHeight) + "px";
  }, [val]);

  const submit = () => {
    if (!val.trim() || disabled) return;
    onSend(val.trim());
    setVal("");
  };

  const hasText = val.trim().length > 0;

  const R = 6;
  const C = 2 * Math.PI * R;
  const ringPct = Math.max(0, Math.min(1, contextUsed));
  const ringColor =
    ringPct > 0.85
      ? "oklch(0.65 0.18 30)"
      : ringPct > 0.65
        ? "oklch(0.72 0.16 80)"
        : "var(--accent)";

  return (
    <div className="composer-wrap">
      <div className={`composer ${approval ? "has-approval" : ""} ${isStreaming ? "is-streaming" : ""}`}>
        <Collapsible open={!!approval} duration={480}>
          {approval && (
            <div className="comp-approval" key={approval.approvalId}>
              <div className="comp-approval-body">
                <div className="comp-approval-head">
                  <span className="comp-approval-kind">{approval.kind}</span>
                  <span className="comp-approval-title">{approval.title}</span>
                </div>
                {approval.detail && <div className="comp-approval-detail">{approval.detail}</div>}
              </div>
              <div className="comp-approval-actions">
                <button
                  className="comp-approval-btn deny"
                  onClick={() => onApprovalDecision("denied")}
                >
                  Deny
                </button>
                <button
                  className="comp-approval-btn approve"
                  onClick={() => onApprovalDecision("approved")}
                >
                  Approve
                </button>
              </div>
            </div>
          )}
        </Collapsible>

        <div className="comp-row">
          <button className="comp-add" title="Add" type="button">
            <IconPlus size={14} />
          </button>
          <textarea
            ref={ref}
            value={val}
            onChange={(e) => setVal(e.target.value)}
            placeholder="Ask anything…"
            rows={1}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <div className="comp-action">
            {isStreaming ? (
              <button className="comp-btn comp-stop" onClick={onStop} title="Stop" key="stop">
                <IconStop size={11} />
              </button>
            ) : hasText ? (
              <button className="comp-btn comp-send" onClick={submit} title="Send" key="send">
                <IconArrowUp size={13} />
              </button>
            ) : (
              <button className="comp-btn comp-mic" title="Voice" key="mic">
                <IconMic size={14} />
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="comp-foot">
        <div
          className={`comp-ctx ${ctxHover ? "is-hover" : ""}`}
          onMouseEnter={() => setCtxHover(true)}
          onMouseLeave={() => setCtxHover(false)}
        >
          <svg className="comp-ring" viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="8" cy="8" r={R} fill="none" stroke="var(--hairline-strong)" strokeWidth="1.5" />
            <circle
              cx="8"
              cy="8"
              r={R}
              fill="none"
              stroke={ringColor}
              strokeWidth="1.5"
              strokeDasharray={C}
              strokeDashoffset={C * (1 - ringPct)}
              strokeLinecap="round"
              transform="rotate(-90 8 8)"
              style={{ transition: "stroke-dashoffset 0.5s var(--ease)" }}
            />
          </svg>
          <span className="comp-ctx-label">
            <span className="comp-ctx-pct">{Math.round(ringPct * 100)}%</span>
            <span className="comp-ctx-detail">
              <span className="comp-ctx-tokens">{contextTokens}</span>
              <span className="comp-ctx-of">/ {contextMax}</span>
            </span>
          </span>
        </div>

        <span className="comp-foot-sep" />

        <ModeSwitch value={mode} onChange={onModeChange} />

        <div className="comp-meta">
          <span className="comp-meta-pip" />
          <span className="comp-meta-model">{model}</span>
          <span className="comp-meta-dot">·</span>
          <span className={`comp-meta-effort comp-meta-effort-${reasoningEffort}`}>
            <span className="comp-meta-effort-bars" aria-hidden="true">
              <i />
              <i />
              <i />
            </span>
            <span>{reasoningEffort}</span>
          </span>
        </div>
      </div>
    </div>
  );
}
