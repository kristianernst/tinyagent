import { type FormEvent, useEffect, useMemo, useState } from "react";
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
import { AgentOrb } from "./AgentOrb";
import type { Artifact } from "./lib/useRun";
import type { GitFileStatus, GitSnapshot, WorkspaceSummary } from "./lib/api";
import { diffLineClass } from "./components";

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

export type Conversation = { id: string; title: string; time: string; running?: boolean };
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
            <AgentOrb seed={activeWorkspaceId || "tinyagent"} running={false} size={13} />
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
                            <AgentOrb seed={c.id} running={!!c.running} size={14} />
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
  git,
  workspaceFiles,
  workspaceName,
}: {
  open: boolean;
  onToggle: () => void;
  artifacts: Artifact[];
  git: GitSnapshot | null;
  workspaceFiles: string[];
  workspaceName: string;
}) {
  const [activeTab, setActiveTab] = useState<"diffs" | "files" | "artifacts">("diffs");
  const changedCount = git?.files.length ?? 0;
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
              aria-selected={activeTab === "diffs"}
              className={`sb-tab ${activeTab === "diffs" ? "is-active" : ""}`}
              onClick={() => setActiveTab("diffs")}
            >
              Diffs
              <span className="sb-tab-count">{changedCount}</span>
            </button>
            <button
              role="tab"
              aria-selected={activeTab === "files"}
              className={`sb-tab ${activeTab === "files" ? "is-active" : ""}`}
              onClick={() => setActiveTab("files")}
            >
              Files
              <span className="sb-tab-count">{workspaceFiles.length}</span>
            </button>
            <button
              role="tab"
              aria-selected={activeTab === "artifacts"}
              className={`sb-tab ${activeTab === "artifacts" ? "is-active" : ""}`}
              onClick={() => setActiveTab("artifacts")}
            >
              Artifacts
              <span className="sb-tab-count">{artifacts.length}</span>
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
          {activeTab === "diffs" && <DiffsPanel git={git} />}
          {activeTab === "files" && <FilesPanel files={workspaceFiles} workspaceName={workspaceName} />}
          {activeTab === "artifacts" && <ArtifactsPanel artifacts={artifacts} />}
        </div>
      </div>
    </aside>
  );
}

function gitStatusLabel(file: GitFileStatus) {
  const labels: Record<GitFileStatus["status"], string> = {
    added: "A",
    modified: "M",
    deleted: "D",
    renamed: "R",
    untracked: "?",
    copied: "C",
    typechange: "T",
    unknown: "•",
  };
  return labels[file.status];
}

function splitDiffByFile(diff: string): Map<string, string> {
  const out = new Map<string, string>();
  if (!diff) return out;
  const lines = diff.split("\n");
  let currentKey: string | null = null;
  let currentLines: string[] = [];
  const flush = () => {
    if (currentKey !== null) out.set(currentKey, currentLines.join("\n"));
  };
  for (const line of lines) {
    const match = line.match(/^diff --git a\/(.+?) b\/(.+)$/);
    if (match) {
      flush();
      currentKey = match[2] === "/dev/null" ? match[1] : match[2];
      currentLines = [line];
    } else if (currentKey !== null) {
      currentLines.push(line);
    }
  }
  flush();
  return out;
}

function DiffsPanel({ git }: { git: GitSnapshot | null }) {
  const changes = git?.files ?? [];
  const branchLabel =
    git?.isRepo && git.branch
      ? [git.branch, git.ahead ? `↑${git.ahead}` : "", git.behind ? `↓${git.behind}` : ""]
          .filter(Boolean)
          .join(" ")
      : "";
  const diffByFile = useMemo(() => splitDiffByFile(git?.diff ?? ""), [git?.diff]);

  if (!git) return <SidePanelEmpty title="Checking git…" body="Diffs will appear here for git workspaces." />;
  if (git.error) return <SidePanelEmpty title="Git unavailable" body={git.error} />;
  if (!git.isRepo) return <SidePanelEmpty title="Not a git repo" body="Open a workspace inside a git checkout to see diffs here." />;
  if (git.clean) return <SidePanelEmpty title="Working tree clean" body={branchLabel || "No local changes."} />;

  return (
    <div className="sidePanel">
      {branchLabel && (
        <div className="sidePanel-head">
          <span className="sidePanel-label">branch</span>
          <span className="sidePanel-value">{branchLabel}</span>
        </div>
      )}
      <div className="sidePanel-head">
        <span className="sidePanel-label">
          {changes.length === 1 ? "1 changed file" : `${changes.length} changed files`}
        </span>
      </div>
      <ul className="diffFiles">
        {changes.map((file) => (
          <DiffFileRow
            key={`${file.path}-${file.oldPath ?? ""}`}
            file={file}
            diff={diffByFile.get(file.path) ?? (file.oldPath ? diffByFile.get(file.oldPath) : undefined)}
          />
        ))}
      </ul>
      {git.diffTruncated && (
        <div className="sidePanel-note">
          Diff truncated. Refresh after committing or narrowing the change set.
        </div>
      )}
    </div>
  );
}

function DiffFileRow({ file, diff }: { file: GitFileStatus; diff?: string }) {
  const [open, setOpen] = useState(false);
  const hasDiff = !!diff;
  const label = file.oldPath ? `${file.oldPath} → ${file.path}` : file.path;
  const lines = hasDiff ? diff.split("\n") : [];
  return (
    <li className={`diffFile status-${file.status}${open ? " open" : ""}`}>
      <div className="diffFile-headRow">
        <button
          type="button"
          className="diffFile-head"
          onClick={() => {
            if (hasDiff) setOpen((value) => !value);
          }}
          disabled={!hasDiff}
          title={label}
          aria-expanded={hasDiff ? open : undefined}
        >
          <span className="diffFile-chev" aria-hidden="true">
            {hasDiff ? (open ? "▾" : "▸") : "·"}
          </span>
          <span className="sideList-badge">{gitStatusLabel(file)}</span>
          <span className="sideList-name">{label}</span>
        </button>
      </div>
      {open && hasDiff && (
        <pre className="diffFile-body" aria-label={`${file.path} diff`}>
          {lines.map((line, index) => (
            <div key={index} className={`diffLine ${diffLineClass(line)}`}>
              {line || " "}
            </div>
          ))}
        </pre>
      )}
    </li>
  );
}

type FileNode = { name: string; isFile: boolean; path: string; children: FileNode[] };

function buildFileTree(paths: string[]): FileNode {
  const root: FileNode = { name: "", isFile: false, path: "", children: [] };
  for (const path of paths) {
    const parts = path.split("/").filter(Boolean);
    if (parts.length === 0) continue;
    let current = root;
    for (let index = 0; index < parts.length; index++) {
      const isLast = index === parts.length - 1;
      const name = parts[index];
      let child = current.children.find((candidate) => candidate.name === name);
      if (!child) {
        child = { name, isFile: isLast, path: parts.slice(0, index + 1).join("/"), children: [] };
        current.children.push(child);
      } else if (isLast) {
        child.isFile = true;
      }
      current = child;
    }
  }
  const sort = (node: FileNode) => {
    node.children.sort((a, b) => {
      if (a.isFile !== b.isFile) return a.isFile ? 1 : -1;
      return a.name.localeCompare(b.name);
    });
    node.children.forEach(sort);
  };
  sort(root);
  return root;
}

function FilesPanel({ files, workspaceName }: { files: string[]; workspaceName: string }) {
  const tree = useMemo(() => buildFileTree(files), [files]);
  if (files.length === 0) {
    return (
      <SidePanelEmpty
        title="No files yet"
        body={
          workspaceName
            ? `${workspaceName} is empty or still loading.`
            : "File listing will appear here once the workspace finishes loading."
        }
      />
    );
  }
  return (
    <div className="sidePanel">
      {workspaceName && (
        <div className="sidePanel-head">
          <span className="sidePanel-label">workspace</span>
          <span className="sidePanel-value">{workspaceName}</span>
        </div>
      )}
      <div className="sidePanel-head">
        <span className="sidePanel-label">{files.length === 1 ? "1 file" : `${files.length} files`}</span>
      </div>
      <ul className="fileTree" role="tree">
        {tree.children.map((node) => (
          <FileTreeNode key={node.path} node={node} depth={0} />
        ))}
      </ul>
    </div>
  );
}

function FileTreeNode({ node, depth }: { node: FileNode; depth: number }) {
  const [open, setOpen] = useState(depth === 0 && !node.isFile);
  const padding = 8 + depth * 12;
  if (node.isFile) {
    return (
      <li className="fileTree-file fileTree-row" title={node.path}>
        <span className="fileTree-rowMain" style={{ paddingLeft: padding }}>
          <span className="fileTree-icon" aria-hidden="true">
            ·
          </span>
          <span className="fileTree-name">{node.name}</span>
        </span>
      </li>
    );
  }
  return (
    <li className="fileTree-folder">
      <button
        type="button"
        className="fileTree-folderHead"
        style={{ paddingLeft: padding }}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className="fileTree-chev" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
        <span className="fileTree-name">{node.name}</span>
      </button>
      {open && (
        <ul role="group">
          {node.children.map((child) => (
            <FileTreeNode key={child.path} node={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

function SidePanelEmpty({ title, body }: { title: string; body: string }) {
  return (
    <div className="sidePanel-empty">
      <div className="sidePanel-empty-title">{title}</div>
      <p>{body}</p>
    </div>
  );
}

function ArtifactsPanel({ artifacts }: { artifacts: Artifact[] }) {
  if (artifacts.length === 0) {
    return (
      <div className="sb-empty">
        <div className="sb-empty-glyph">
          <IconBolt size={18} />
        </div>
        <div className="sb-empty-title">No artifacts yet</div>
        <div className="sb-empty-sub">Files the agent creates or edits will appear here.</div>
      </div>
    );
  }
  return (
    <div className="sb-artifacts">
      {artifacts.map((artifact, index) => (
        <ArtifactItem key={artifact.id} artifact={artifact} index={index} />
      ))}
    </div>
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
