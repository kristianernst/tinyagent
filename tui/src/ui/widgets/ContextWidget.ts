import type { GitSnapshot, Workspace } from "../../protocol/events";
import type { Theme } from "../theme";
import { makeBox } from "../layout";
import { InfoPanelWidget } from "./InfoPanelWidget";
import { makePanelList } from "./panelStyle";

export class ContextWidget {
  readonly node: any;
  private summary: InfoPanelWidget;
  private files: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.summary = new InfoPanelWidget(opentui, ctx, theme, { compact: true });
    this.files = makePanelList(opentui, ctx, theme, {
      showDescription: false,
      flexGrow: 1,
      minHeight: 4,
      marginTop: 1,
      maxRows: 18,
      maxTextWidth: 52,
    });
    this.node.add?.(this.summary.node);
    this.node.add?.(this.files);
  }

  update(workspace: Workspace | null, files: string[], git: GitSnapshot | null): void {
    const changed = git?.files.length ?? 0;
    const gitValue = git?.isRepo ? `${git.branch ?? "detached"} ${git.clean ? "clean" : "dirty"}` : "not a repo";
    const gitDetail = git?.isRepo && !git.clean
      ? `${changed} changed file${changed === 1 ? "" : "s"}` + (git.ahead ? ` · ahead ${git.ahead}` : "") + (git.behind ? ` · behind ${git.behind}` : "")
      : "working tree has no reported changes";
    this.summary.update({
      eyebrow: "workspace context",
      rows: [
        {
          label: "workspace",
          value: workspace?.name ?? "none",
          detail: workspace?.root ? shortenPath(workspace.root) : "no active workspace",
          tone: "accent",
        },
        {
          label: "git",
          value: gitValue,
          detail: gitDetail,
          tone: git?.isRepo && !git.clean ? "warning" : "default",
        },
        {
          label: "files",
          value: String(files.length),
          detail: "file mentions",
        },
      ],
    });
    if (this.files && "options" in this.files) {
      const changed = new Map<string, string>(git?.files?.map((file) => [file.path, file.status]) ?? []);
      this.files.options = files.slice(0, 500).map((path) => ({
        name: path,
        rightMeta: statusLabel(changed.get(path)),
        description: "",
        value: path,
      }));
    }
  }
}

function shortenPath(path: string): string {
  const home = process.env.HOME;
  if (home && path.startsWith(home)) return `~${path.slice(home.length)}`;
  if (/^\/Users\/[^/]+(\/|$)/.test(path)) return path.replace(/^\/Users\/[^/]+/, "~");
  return path;
}

function statusLabel(status: string | undefined): string {
  if (!status) return "";
  const map: Record<string, string> = {
    modified: "modified",
    added: "added",
    deleted: "deleted",
    renamed: "renamed",
    untracked: "untracked",
  };
  return map[status] ?? status;
}
