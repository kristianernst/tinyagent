import type { GitSnapshot, Workspace } from "../../protocol/events";
import type { Theme } from "../theme";
import { makeBox, makeSelect, makeText } from "../layout";

export class ContextWidget {
  readonly node: any;
  private header: any;
  private files: any;
  private status: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.header = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
    this.status = makeText(opentui, ctx, { content: "", fg: theme.warning, marginTop: 1 });
    this.files = makeSelect(opentui, ctx, {
      options: [],
      showDescription: false,
      backgroundColor: theme.surface,
      textColor: theme.text,
      selectedBackgroundColor: theme.selectionBg,
      selectedTextColor: theme.selectionFg,
      showScrollIndicator: true,
      wrapSelection: true,
      focusable: true,
      flexGrow: 1,
      minHeight: 4,
      marginTop: 1,
    });
    this.node.add?.(this.header);
    this.node.add?.(this.status);
    this.node.add?.(this.files);
  }

  update(workspace: Workspace | null, files: string[], git: GitSnapshot | null): void {
    const head = [
      `Workspace: ${workspace?.name ?? "none"}`,
      workspace?.root ? `Root: ${workspace.root}` : "",
      `Files: ${files.length}`,
      git?.isRepo ? `Git: ${git.branch ?? "detached"} ${git.clean ? "clean" : "dirty"}` : "Git: not a repo",
    ]
      .filter(Boolean)
      .join("\n");
    if (this.header && this.header.content !== undefined) this.header.content = head;
    if (this.status && this.status.content !== undefined) {
      this.status.content = git?.isRepo && !git.clean
        ? `${git.files.length} changed file${git.files.length === 1 ? "" : "s"}` + (git.ahead ? ` · ahead ${git.ahead}` : "") + (git.behind ? ` · behind ${git.behind}` : "")
        : "";
    }
    if (this.files && "options" in this.files) {
      const changed = new Map<string, string>(git?.files?.map((file) => [file.path, file.status]) ?? []);
      this.files.options = files.slice(0, 500).map((path) => ({
        name: `${changed.get(path)?.[0]?.toUpperCase() ?? " "} ${path}`,
        description: "",
        value: path,
      }));
    }
  }
}
