import { type FormEvent, useEffect, useState } from "react";
import {
  IconBolt,
  IconChartArt,
  IconChev,
  IconCode,
  IconFile,
  IconFolder,
  IconImage,
  IconMaximize,
  IconPlus,
  IconSearch,
  IconSettings,
  IconSidebarL,
  IconSidebarR,
} from "./icons";
import type { Artifact } from "./lib/useRun";
import type { WorkspaceSummary } from "./lib/api";

export function SidebarToggle({
  side,
  open,
  onClick,
}: {
  side: "left" | "right";
  open: boolean;
  onClick: () => void;
}) {
  const Ico = side === "left" ? IconSidebarL : IconSidebarR;
  return (
    <button
      className={`sb-toggle sb-toggle-${side} ${open ? "is-open" : ""}`}
      onClick={onClick}
      title={`${open ? "Hide" : "Show"} ${side} sidebar`}
      aria-label={`Toggle ${side} sidebar`}
    >
      <Ico />
    </button>
  );
}

export type Conversation = { id: string; title: string; time: string };
type Project = { id: string; name: string; conversations: Conversation[] };

export function LeftSidebar({
  open,
  onToggle,
  activeChat,
  conversations,
  workspaces,
  activeWorkspaceId,
  onPickChat,
  onPickWorkspace,
  onAddWorkspace,
  onNewChat,
}: {
  open: boolean;
  onToggle: () => void;
  activeChat: string;
  conversations: Conversation[];
  workspaces: WorkspaceSummary[];
  activeWorkspaceId: string;
  onPickChat: (id: string) => void;
  onPickWorkspace: (id: string) => void;
  onAddWorkspace: (path: string) => Promise<void>;
  onNewChat: () => void;
}) {
  const projects: Project[] = workspaces.map((workspace) => ({
    id: workspace.workspace_id,
    name: workspace.name,
    conversations: workspace.workspace_id === activeWorkspaceId ? conversations : [],
  }));
  const [openProjects, setOpenProjects] = useState<Set<string>>(() => new Set());
  const [workspacePath, setWorkspacePath] = useState("");
  const [workspaceError, setWorkspaceError] = useState("");
  const [addingWorkspace, setAddingWorkspace] = useState(false);
  useEffect(() => {
    if (!activeWorkspaceId) return;
    setOpenProjects((current) => new Set(current).add(activeWorkspaceId));
  }, [activeWorkspaceId]);
  const toggleProject = (id: string) =>
    setOpenProjects((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const submitWorkspace = async (event: FormEvent) => {
    event.preventDefault();
    const path = workspacePath.trim();
    if (!path || addingWorkspace) return;
    setWorkspaceError("");
    setAddingWorkspace(true);
    try {
      await onAddWorkspace(path);
      setWorkspacePath("");
    } catch (err) {
      setWorkspaceError(err instanceof Error ? err.message : String(err));
    } finally {
      setAddingWorkspace(false);
    }
  };

  return (
    <aside
      className={`sidebar sidebar-left ${open ? "is-open" : "is-closed"}`}
      aria-hidden={!open}
    >
      <div className="sb-inner">
        <div className="sb-head">
          <div className="brand">
            <span className="dot" />
            <span>tinyagent</span>
          </div>
          <SidebarToggle side="left" open={open} onClick={onToggle} />
        </div>

        <button className="sb-new" onClick={onNewChat}>
          <IconPlus size={13} />
          <span>New chat</span>
          <span className="kbd">⌘K</span>
        </button>

        <div className="sb-search">
          <IconSearch size={12} />
          <input placeholder="Search chats" />
        </div>

        <div className="sb-scroll">
          <div className="sb-section-label">Projects</div>
          <form className="sb-workspace-form" onSubmit={submitWorkspace}>
            <input
              value={workspacePath}
              onChange={(event) => setWorkspacePath(event.target.value)}
              placeholder="Workspace path"
            />
            <button type="submit" title="Add workspace" disabled={addingWorkspace || !workspacePath.trim()}>
              <IconPlus size={12} />
            </button>
          </form>
          {workspaceError && <div className="sb-workspace-error">{workspaceError}</div>}
          {projects.map((p, pi) => {
            const isOpen = openProjects.has(p.id);
            return (
              <div
                key={p.id}
                className={`sb-project ${isOpen ? "is-open" : ""}`}
                style={{ ["--i" as any]: pi }}
              >
                <button
                  className={`sb-project-head ${activeWorkspaceId === p.id ? "is-active" : ""}`}
                  onClick={() => {
                    onPickWorkspace(p.id);
                    toggleProject(p.id);
                  }}
                >
                  <IconChev className="sb-chev" size={11} />
                  <IconFolder size={13} />
                  <span className="sb-project-name">{p.name}</span>
                  <span className="sb-count">{p.conversations.length}</span>
                </button>
                <div className="sb-collapsible" data-open={isOpen}>
                  <div className="sb-collapsible-inner">
                    <div className="sb-convs">
                      {p.conversations.length === 0 ? (
                        <div className="sb-empty sb-empty-compact">No conversations yet</div>
                      ) : (
                        p.conversations.map((c, ci) => (
                          <button
                            key={c.id}
                            className={`sb-conv ${activeChat === c.id ? "is-active" : ""}`}
                            onClick={() => onPickChat(c.id)}
                            style={{ ["--ci" as any]: ci }}
                          >
                            <span className="sb-conv-title">{c.title}</span>
                            <span className="sb-conv-time">{c.time}</span>
                          </button>
                        ))
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="sb-foot">
          <button className="sb-foot-btn">
            <IconSettings size={14} strokeWidth={2} />
            <span>Settings</span>
          </button>
        </div>
      </div>
    </aside>
  );
}

export function RightSidebar({
  open,
  onToggle,
  artifacts,
}: {
  open: boolean;
  onToggle: () => void;
  artifacts: Artifact[];
}) {
  const [activeTab, setActiveTab] = useState<"files">("files");
  return (
    <aside
      className={`sidebar sidebar-right ${open ? "is-open" : "is-closed"}`}
      aria-hidden={!open}
    >
      <div className="sb-inner">
        <div className="sb-head sb-head-right">
          <div className="sb-tabs" role="tablist">
            <button
              role="tab"
              aria-selected={activeTab === "files"}
              className={`sb-tab ${activeTab === "files" ? "is-active" : ""}`}
              onClick={() => setActiveTab("files")}
            >
              Files
              <span className="sb-tab-count">{artifacts.length}</span>
            </button>
            <button className="sb-tab-add" title="New tab" type="button">
              <IconPlus size={12} strokeWidth={2.25} />
            </button>
          </div>
          <div className="sb-head-actions">
            <button className="sb-head-icon" title="Maximize" type="button">
              <IconMaximize size={13} strokeWidth={2} />
            </button>
            <SidebarToggle side="right" open={open} onClick={onToggle} />
          </div>
        </div>

        <div className="sb-scroll">
          {artifacts.length === 0 ? (
            <div className="sb-empty">
              <div className="sb-empty-glyph">
                <IconBolt size={18} />
              </div>
              <div className="sb-empty-title">No artifacts yet</div>
              <div className="sb-empty-sub">Files the agent creates or edits will appear here.</div>
            </div>
          ) : (
            <div className="sb-artifacts">
              {artifacts.map((a, i) => (
                <ArtifactItem key={a.id} artifact={a} index={i} />
              ))}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

function ArtifactItem({ artifact, index }: { artifact: Artifact; index: number }) {
  const Ico =
    artifact.kind === "chart"
      ? IconChartArt
      : artifact.kind === "image"
        ? IconImage
        : artifact.kind === "code"
          ? IconCode
          : IconFile;
  const content = (
    <>
      <span className="sb-artifact-ico">
        <Ico size={14} strokeWidth={2} />
      </span>
      <span className="sb-artifact-title">{artifact.title}</span>
    </>
  );
  const className = `sb-artifact sb-artifact-${artifact.state || "done"} fade-up-sm`;
  const style = { ["--i" as any]: index };
  if (artifact.href) {
    return (
      <a className={className} style={style} title={artifact.title} href={artifact.href} target="_blank" rel="noreferrer">
        {content}
      </a>
    );
  }
  return (
    <button className={className} style={style} title={artifact.title}>
      {content}
    </button>
  );
}
