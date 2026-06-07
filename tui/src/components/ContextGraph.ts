import type { GitSnapshot, Workspace } from "../protocol/events";

export function renderContextGraph(workspace: Workspace | null, files: string[], git: GitSnapshot | null): string {
  const changed = git?.files.length ?? 0;
  const gitValue = git?.isRepo ? `${git.branch ?? "detached"} ${git.clean ? "clean" : "dirty"}` : "not a repo";
  const gitDetail = git?.isRepo && !git.clean
    ? `${changed} changed file${changed === 1 ? "" : "s"}` + (git.ahead ? ` · ahead ${git.ahead}` : "") + (git.behind ? ` · behind ${git.behind}` : "")
    : "working tree has no reported changes";
  return [
    "workspace context",
    row("workspace", workspace?.name ?? "none", workspace?.root ? shortenPath(workspace.root) : "no active workspace"),
    row("git", gitValue, gitDetail),
    row("files", String(files.length), "file mentions"),
  ].join("\n");
}

function row(label: string, value: string, detail: string): string {
  return [`  ▏ ${label.padEnd(14)}${value}`, `    ${detail}`].join("\n");
}

function shortenPath(path: string): string {
  const home = process.env.HOME;
  if (home && path.startsWith(home)) return `~${path.slice(home.length)}`;
  if (/^\/Users\/[^/]+(\/|$)/.test(path)) return path.replace(/^\/Users\/[^/]+/, "~");
  return path;
}
