import type { ExtensionEntry } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox, makeSelect, makeText } from "../layout";

export class ExtensionsWidget {
  readonly node: any;
  private select: any;
  private detail: any;
  private extensions: ExtensionEntry[] = [];

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.select = makeSelect(opentui, ctx, {
      options: [],
      showDescription: true,
      backgroundColor: theme.surface,
      textColor: theme.text,
      selectedBackgroundColor: theme.selectionBg,
      selectedTextColor: theme.selectionFg,
      descriptionColor: theme.textMuted,
      selectedDescriptionColor: theme.text,
      showScrollIndicator: true,
      wrapSelection: true,
      focusable: true,
      minHeight: 4,
      flexGrow: 1,
    });
    this.detail = makeText(opentui, ctx, { content: "No extensions detected.", fg: theme.textMuted, marginTop: 1 });
    this.node.add?.(this.select);
    this.node.add?.(this.detail);
    if (typeof this.select?.on === "function") {
      this.select.on("selectionChanged", (event: any) => {
        const index = event?.index ?? event?.selectedIndex ?? 0;
        this.renderDetail(this.extensions[index]);
      });
    }
  }

  update(extensions: ExtensionEntry[]): void {
    this.extensions = extensions;
    if (!extensions.length) {
      if (this.select && "options" in this.select) this.select.options = [];
      if (this.detail && this.detail.content !== undefined)
        this.detail.content = "No extensions reported by the backend.";
      return;
    }
    if (this.select && "options" in this.select) {
      this.select.options = extensions.map((ext) => ({
        name: `${kindIcon(ext.kind)} ${ext.name}`,
        description: ext.description ?? extensionDescription(ext),
        value: ext.name,
      }));
    }
    this.renderDetail(extensions[0]);
  }

  private renderDetail(ext: ExtensionEntry | undefined): void {
    if (!ext) {
      if (this.detail && this.detail.content !== undefined) this.detail.content = "";
      return;
    }
    const lines = [
      `${kindIcon(ext.kind)} ${ext.name} · ${ext.kind}`,
      ext.servers && ext.servers.length ? `servers: ${ext.servers.join(", ")}` : "",
      typeof ext.enabled === "boolean" ? `enabled: ${ext.enabled ? "yes" : "no"}` : "",
      ext.description ? `\n${ext.description}` : "",
    ].filter(Boolean);
    if (this.detail && this.detail.content !== undefined) this.detail.content = lines.join("\n");
  }
}

export function normalizeExtensions(raw: Array<Record<string, unknown>>): ExtensionEntry[] {
  const out: ExtensionEntry[] = [];
  for (const entry of raw ?? []) {
    const name = String(entry.name ?? "extension");
    let kind: ExtensionEntry["kind"] = "other";
    if (name === "mcp") kind = "mcp";
    else if (name === "lsp") kind = "lsp";
    else if (name === "todo_memory" || name === "product_runtime") kind = "feature";
    const servers = Array.isArray(entry.servers) ? (entry.servers as unknown[]).map(String) : undefined;
    const enabled = typeof entry.enabled === "boolean" ? (entry.enabled as boolean) : undefined;
    out.push({ name, kind, servers, enabled });
  }
  return out;
}

function kindIcon(kind: ExtensionEntry["kind"]): string {
  if (kind === "mcp") return "▤";
  if (kind === "lsp") return "⌘";
  if (kind === "feature") return "✦";
  return "•";
}

function extensionDescription(ext: ExtensionEntry): string {
  if (ext.kind === "mcp") return `Model Context Protocol — ${ext.servers?.length ?? 0} servers`;
  if (ext.kind === "lsp") return `Language servers — ${ext.servers?.length ?? 0} configured`;
  if (ext.kind === "feature") return "Backend feature toggle";
  return "Extension";
}
