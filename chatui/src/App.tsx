import { useCallback, useEffect, useRef, useState } from "react";
import { Composer, TurnView } from "./components";
import type { Mode } from "./components";
import { LeftSidebar, RightSidebar, SidebarToggle } from "./sidebars";
import type { Conversation } from "./sidebars";
import { IconSidebarL, IconSidebarR } from "./icons";
import { useRun } from "./lib/useRun";

const SAMPLE_QUERIES = [
  "List the files in this workspace",
  "Read README.md and summarize it",
  "Search for TODO comments in the code",
  "Show recent git commits",
];

export function App() {
  const {
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
  } = useRun();

  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [mode, setMode] = useState<Mode>("yolo");
  const [pickedChat, setPickedChat] = useState("");

  const threadRef = useRef<HTMLDivElement>(null);

  // gentle auto-scroll using ResizeObserver
  const userScrolledUpRef = useRef(false);
  const animatingRef = useRef(false);
  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    const onScroll = () => {
      if (animatingRef.current) return;
      const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      userScrolledUpRef.current = distFromBottom > 140;
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  const smoothScrollToBottom = useCallback(() => {
    const el = threadRef.current;
    if (!el || userScrolledUpRef.current) return;
    const from = el.scrollTop;
    const to = el.scrollHeight - el.clientHeight;
    if (Math.abs(to - from) < 2) return;
    animatingRef.current = true;
    let start: number | undefined;
    const dur = 480;
    const ease = (t: number) => 1 - Math.pow(1 - t, 3);
    const tick = (ts: number) => {
      if (start === undefined) start = ts;
      const t = Math.min(1, (ts - start) / dur);
      const target = el.scrollHeight - el.clientHeight;
      el.scrollTop = from + (target - from) * ease(t);
      if (t < 1) requestAnimationFrame(tick);
      else animatingRef.current = false;
    };
    requestAnimationFrame(tick);
  }, []);

  useEffect(() => {
    const el = threadRef.current;
    if (!el) return;
    let scheduled = false;
    const ro = new ResizeObserver(() => {
      if (scheduled) return;
      scheduled = true;
      requestAnimationFrame(() => {
        scheduled = false;
        smoothScrollToBottom();
      });
    });
    Array.from(el.children).forEach((c) => ro.observe(c));
    const mo = new MutationObserver(() => {
      Array.from(el.children).forEach((c) => {
        try {
          ro.observe(c);
        } catch {
          /* ignore */
        }
      });
    });
    mo.observe(el, { childList: true });
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  }, [smoothScrollToBottom]);

  const isEmpty = turns.length === 0;
  const approvalMode = mode === "yolo" ? "yolo" : "on-request";
  const conversations: Conversation[] = sessions.map((session) => ({
    id: session.session_id,
    title: session.title || "New conversation",
    time: formatSessionTime(session.updated_at),
  }));

  const onSend = (text: string) => send(text, approvalMode);

  const newChat = () => {
    if (phase !== "idle") void stop();
    newSession();
  };

  return (
    <div className="shell">
      <LeftSidebar
        open={leftOpen}
        onToggle={() => setLeftOpen((o) => !o)}
        activeChat={activeSessionId ?? pickedChat}
        conversations={conversations}
        onPickChat={setPickedChat}
        onNewChat={newChat}
      />

      <div className="app">
        <div className="topbar">
          <div className="topbar-left">
            {!leftOpen && (
              <button
                className="floating-toggle"
                onClick={() => setLeftOpen(true)}
                title="Show sidebar"
              >
                <IconSidebarL />
              </button>
            )}
          </div>
          <div className="topbar-title">
            {turns.length > 0 ? turns[0].user.slice(0, 60) : "New conversation"}
          </div>
          <div className="topbar-right">
            <span className="topbar-date">
              {new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" })}
            </span>
            {!rightOpen && (
              <button
                className="floating-toggle"
                onClick={() => setRightOpen(true)}
                title="Show artifacts"
              >
                <IconSidebarR />
              </button>
            )}
          </div>
        </div>

        <div className="thread thread-mask" ref={threadRef}>
          {isEmpty ? (
            <div className="empty fade-up">
              <h1>Hello.</h1>
              <p>Ask the agent to inspect your workspace, run commands, or edit files.</p>
              <div className="suggest-row">
                {SAMPLE_QUERIES.map((q, i) => (
                  <button
                    key={i}
                    className="suggest fade-up"
                    style={{ animationDelay: `${0.1 + i * 0.06}s` }}
                    onClick={() => onSend(q)}
                  >
                    {q}
                  </button>
                ))}
              </div>
              {error && (
                <p style={{ marginTop: 24, color: "oklch(0.55 0.16 25)", fontSize: 13 }}>
                  {error}
                </p>
              )}
            </div>
          ) : (
            turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
          )}
        </div>

        <Composer
          onSend={onSend}
          disabled={phase !== "idle"}
          isStreaming={phase !== "idle"}
          onStop={stop}
          approval={approval}
          onApprovalDecision={(decision) => respondToApproval(decision)}
          mode={mode}
          onModeChange={setMode}
        />
      </div>

      <RightSidebar
        open={rightOpen}
        onToggle={() => setRightOpen((o) => !o)}
        artifacts={artifacts}
      />
    </div>
  );
}

function formatSessionTime(value: string): string {
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return "";
  const deltaMs = Date.now() - timestamp;
  if (deltaMs < 60_000) return "now";
  if (deltaMs < 3_600_000) return `${Math.max(1, Math.floor(deltaMs / 60_000))}m`;
  if (deltaMs < 86_400_000) return `${Math.max(1, Math.floor(deltaMs / 3_600_000))}h`;
  return new Date(timestamp).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}
