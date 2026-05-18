import type { Theme } from "../theme";
import { makeBox } from "../layout";

export type ResizeListener = (railWidth: number) => void;

export class DividerWidget {
  readonly node: any;
  private listener: ResizeListener | null = null;
  private railWidth = 56;
  private dragging = false;
  private startX = 0;
  private startWidth = 56;
  private minWidth = 32;
  private maxWidth = 120;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, {
      width: 1,
      backgroundColor: theme.border,
      focusable: false,
    });
    if (this.node && "onMouseDown" in this.node) {
      this.node.onMouseDown = (event: any) => {
        this.dragging = true;
        this.startX = event?.x ?? 0;
        this.startWidth = this.railWidth;
        if (this.node && "backgroundColor" in this.node) this.node.backgroundColor = theme.borderFocus;
      };
    }
    if (this.node && "onMouseDrag" in this.node) {
      this.node.onMouseDrag = (event: any) => {
        if (!this.dragging) return;
        const x = event?.x ?? this.startX;
        const delta = this.startX - x;
        const next = Math.max(this.minWidth, Math.min(this.maxWidth, this.startWidth + delta));
        this.setWidth(next);
      };
    }
    if (this.node && "onMouseUp" in this.node) {
      this.node.onMouseUp = () => {
        this.dragging = false;
        if (this.node && "backgroundColor" in this.node) this.node.backgroundColor = theme.border;
      };
    }
  }

  setListener(listener: ResizeListener): void {
    this.listener = listener;
  }

  setWidth(width: number): void {
    if (width === this.railWidth) return;
    this.railWidth = width;
    this.listener?.(width);
  }

  getWidth(): number {
    return this.railWidth;
  }
}
