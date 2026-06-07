import { glyphs } from "../../design/glyphs";
import { makeBox, makeText, type BoxProps } from "../layout";
import type { Theme } from "../theme";

export type PanelListOption = {
  name: string;
  description?: string;
  rightMeta?: string;
  value: string;
};

type PanelListProps = BoxProps & {
  showDescription?: boolean;
  itemSpacing?: number;
  maxRows?: number;
  maxTextWidth?: number;
  commitOnClick?: boolean;
};

type PanelListEvent = "selectionChanged" | "itemSelected";
type PanelListHandler = (event: { index: number; selectedIndex: number; option?: PanelListOption; value?: string }) => void;

export function makePanelList(opentui: any, ctx: any, theme: Theme, props: PanelListProps = {}): any {
  const {
    showDescription = false,
    itemSpacing = 0,
    maxRows = 100,
    maxTextWidth = 42,
    commitOnClick = false,
    ...layout
  } = props;
  const node = makeBox(opentui, ctx, {
    flexDirection: "column",
    backgroundColor: theme.surfaceOverlay ?? theme.surface,
    focusable: true,
    ...layout,
  });
  const handlers = new Map<PanelListEvent, PanelListHandler[]>();
  const rows: any[] = [];
  let options: PanelListOption[] = [];
  let selectedIndex = 0;
  let hoverIndex: number | null = null;

  const emit = (event: PanelListEvent) => {
    const option = options[selectedIndex];
    for (const handler of handlers.get(event) ?? []) {
      handler({ index: selectedIndex, selectedIndex, option, value: option?.value });
    }
  };

  const clearRows = () => {
    for (const row of rows.splice(0)) node.remove?.(row.id ?? row);
  };

  const render = () => {
    clearRows();
    if (!options.length) {
      const empty = makeText(opentui, ctx, { content: "", fg: theme.textMuted });
      node.add?.(empty);
      rows.push(empty);
      return;
    }
    const visibleStart = Math.min(Math.max(0, selectedIndex - maxRows + 1), Math.max(0, options.length - maxRows));
    const visible = options.slice(visibleStart, visibleStart + maxRows);
    for (let localIndex = 0; localIndex < visible.length; localIndex++) {
      const index = visibleStart + localIndex;
      const option = visible[localIndex]!;
      const selected = index === selectedIndex;
      const hovered = index === hoverIndex && !selected;
      const row = makeBox(opentui, ctx, {
        flexDirection: "column",
        minHeight: showDescription && option.description ? 2 : 1,
        paddingX: 1,
        marginBottom: itemSpacing,
        backgroundColor: selected ? theme.selectionBg : hovered ? theme.rowHoverBg : theme.surfaceOverlay ?? theme.surface,
        focusable: true,
        cursor: "pointer",
      });
      const prefix = selected ? `${glyphs.caretStream} ` : hovered ? `${glyphs.hover} ` : "  ";
      row.add?.(
        makeText(opentui, ctx, {
          content: renderTitle(prefix, option.name, option.rightMeta ?? "", maxTextWidth),
          fg: selected ? theme.selectionFg : hovered ? theme.rowHoverFg : theme.text,
        }),
      );
      if (showDescription && option.description) {
        row.add?.(
          makeText(opentui, ctx, {
            content: `  ${truncate(option.description, maxTextWidth)}`,
            fg: selected ? theme.text : theme.textMuted,
          }),
        );
      }
      row.onMouseOver = () => {
        if (hoverIndex === index) return;
        hoverIndex = index;
        render();
      };
      row.onMouseOut = () => {
        if (hoverIndex !== index) return;
        hoverIndex = null;
        render();
      };
      row.onMouseDown = (event: any) => {
        if (event?.type !== "down" || (event.button !== 0 && event.button != null)) return;
        hoverIndex = null;
        selectedIndex = index;
        render();
        emit("selectionChanged");
        if (commitOnClick) node.commit?.();
      };
      node.add?.(row);
      rows.push(row);
    }
    const overflow = options.length - visible.length;
    if (overflow > 0) {
      const more = makeText(opentui, ctx, {
        content: visibleStart > 0 ? `  +${visibleStart} above · +${options.length - visibleStart - visible.length} below` : `  +${overflow} more`,
        fg: theme.textSubtle,
      });
      node.add?.(more);
      rows.push(more);
    }
  };

  const move = (delta: number) => {
    if (!options.length) return false;
    selectedIndex = (selectedIndex + delta + options.length) % options.length;
    render();
    emit("selectionChanged");
    return true;
  };

  Object.defineProperty(node, "options", {
    get: () => options,
    set: (next: PanelListOption[]) => {
      options = Array.isArray(next) ? next : [];
      selectedIndex = Math.min(selectedIndex, Math.max(0, options.length - 1));
      hoverIndex = null;
      render();
    },
    configurable: true,
  });
  Object.defineProperty(node, "selectedIndex", {
    get: () => selectedIndex,
    set: (next: number) => {
      selectedIndex = Math.max(0, Math.min(options.length - 1, next));
      render();
      emit("selectionChanged");
    },
    configurable: true,
  });
  node.on = (event: PanelListEvent, handler: PanelListHandler) => {
    handlers.set(event, [...(handlers.get(event) ?? []), handler]);
  };
  node.off = (event: PanelListEvent, handler: PanelListHandler) => {
    handlers.set(event, (handlers.get(event) ?? []).filter((item) => item !== handler));
  };
  node.moveUp = () => move(-1);
  node.moveDown = () => move(1);
  node.commit = () => {
    if (!options.length) return false;
    emit("itemSelected");
    return true;
  };
  node.selectedValue = () => options[selectedIndex]?.value ?? "";
  render();
  return node;
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, Math.max(0, max - 1))}…`;
}

function renderTitle(prefix: string, name: string, rightMeta: string, width: number): string {
  const left = `${prefix}${name}`;
  if (!rightMeta) return truncate(left, width);
  const gap = 2;
  const maxLeft = Math.max(0, width - rightMeta.length - gap);
  const clipped = truncate(left, maxLeft);
  return `${clipped}${" ".repeat(Math.max(gap, width - clipped.length - rightMeta.length))}${rightMeta}`;
}
