import type { ExtensionEntry } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox } from "../layout";
import { InfoPanelWidget } from "./InfoPanelWidget";
import { makePanelList } from "./panelStyle";

export class ExtensionsWidget {
  readonly node: any;
  private select: any;
  private detail: InfoPanelWidget;
  private extensions: ExtensionEntry[] = [];

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.select = makePanelList(opentui, ctx, theme, {
      showDescription: true,
      minHeight: 4,
      height: 10,
      flexShrink: 0,
      maxRows: 4,
      maxTextWidth: 52,
    });
    this.detail = new InfoPanelWidget(opentui, ctx, theme, { compact: true, minHeight: 11 });
    this.node.add?.(this.select);
    this.node.add?.(this.detail.node);
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
      this.detail.update({
        eyebrow: "extension detail",
        rows: [
          {
            label: "status",
            value: "empty",
            detail: "no extensions reported",
            tone: "muted",
          },
        ],
      });
      return;
    }
    if (this.select && "options" in this.select) {
      this.select.options = extensions.map((ext) => ({
        name: extensionName(ext),
        rightMeta: extensionMeta(ext),
        description: extensionListDetail(ext),
        value: ext.name,
      }));
    }
    this.renderDetail(extensions[0]);
  }

  private renderDetail(ext: ExtensionEntry | undefined): void {
    if (!ext) {
      this.detail.update({
        eyebrow: "extension detail",
        rows: [
          {
            label: "status",
            value: "quiet",
            detail: "choose an extension row",
            tone: "muted",
          },
        ],
      });
      return;
    }
    this.detail.update({
      eyebrow: "extension detail",
      rows: [
        {
          label: "name",
          value: extensionName(ext),
          detail: statusLabel(ext),
          tone: ext.enabled === false ? "muted" : "accent",
        },
        {
          label: "servers",
          value: serverSummary(ext),
          detail: serverDetail(ext),
        },
        {
          label: "purpose",
          value: purposeValue(ext),
          detail: purposeDetail(ext),
          tone: ext.enabled === false ? "warning" : "default",
        },
      ],
    });
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

function extensionMeta(ext: ExtensionEntry): string {
  const count = ext.servers?.length ?? 0;
  if (ext.kind === "mcp" || ext.kind === "lsp") return `${count} ${count === 1 ? "server" : "servers"}`;
  return statusShort(ext);
}

function extensionListDetail(ext: ExtensionEntry): string {
  if (ext.servers?.length) return `servers: ${ext.servers.join(", ")}`;
  if (ext.kind === "feature") return "lifecycle hooks";
  return purposeDetail(ext);
}

function statusLabel(ext: ExtensionEntry): string {
  if (ext.enabled === true) return "enabled";
  if (ext.enabled === false) return "disabled";
  return "status unknown";
}

function statusShort(ext: ExtensionEntry): string {
  if (ext.enabled === true) return "on";
  if (ext.enabled === false) return "off";
  return "unknown";
}

function serverSummary(ext: ExtensionEntry): string {
  if (!ext.servers?.length) return "none";
  return ext.servers.length > 3 ? `${ext.servers.length} configured` : ext.servers.join(", ");
}

function serverDetail(ext: ExtensionEntry): string {
  if (ext.servers?.length) return `${ext.servers.length} ${ext.servers.length === 1 ? "server" : "servers"}`;
  return "no server bindings reported";
}

function purposeValue(ext: ExtensionEntry): string {
  if (ext.kind === "mcp") return "tool access";
  if (ext.kind === "lsp") return "editor intelligence";
  if (ext.kind === "feature") return "app hooks";
  return "extension";
}

function purposeDetail(ext: ExtensionEntry): string {
  if (ext.kind === "mcp") return "local tool bridge";
  if (ext.kind === "lsp") return "hover · symbols · diagnostics";
  if (ext.kind === "feature") return "lifecycle hooks";
  if (ext.description) return humanDescription(ext.description);
  return "no description";
}

function extensionName(ext: ExtensionEntry): string {
  if (ext.kind === "feature" && ext.name === "product_runtime") return "app hooks";
  return displayName(ext.name);
}

function displayName(value: string): string {
  return value.replace(/[_-]+/g, " ");
}

function humanDescription(value: string): string {
  return value.replace(/^Experimental\s+/i, "").replace(/\.$/, "");
}
