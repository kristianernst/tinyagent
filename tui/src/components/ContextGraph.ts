import type { GitSnapshot, Workspace } from "../protocol/events";

export function renderContextGraph(workspace: Workspace | null, files: string[], git: GitSnapshot | null): string {
  return [
    `Workspace: ${workspace?.name ?? "none"}`,
    `Root: ${workspace?.root ?? ""}`,
    `Files: ${files.length}`,
    `Git: ${git?.isRepo ? `${git.branch ?? "detached"} ${git.clean ? "clean" : "dirty"}` : "not a repo"}`,
  ].join("\n");
}
