import type { Theme } from "./theme";

export type BoxProps = Record<string, unknown>;

export const COMPACT_VIEWPORT_WIDTH = 100;

export function isCompactViewport(width: number): boolean {
  return Number.isFinite(width) && width < COMPACT_VIEWPORT_WIDTH;
}

export function makeBox(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode(options);
  return new opentui.BoxRenderable(ctx, options);
}

export function makeText(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode(options);
  return new opentui.TextRenderable(ctx, options);
}

export function makeScrollBox(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode(options);
  return new opentui.ScrollBoxRenderable(ctx, options);
}

export function makeInput(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode(options);
  return new opentui.InputRenderable(ctx, options);
}

export function makeTextarea(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode(options);
  return new opentui.TextareaRenderable(ctx, options);
}

export function makeMarkdown(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui || !opentui.MarkdownRenderable) return makeText(opentui, ctx, { content: String(options.content ?? "") });
  return new opentui.MarkdownRenderable(ctx, options);
}

export function makeDiff(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui || !opentui.DiffRenderable) return makeText(opentui, ctx, { content: String(options.diff ?? "") });
  return new opentui.DiffRenderable(ctx, options);
}

export function syntaxStyleFor(opentui: any, theme: Theme): any | undefined {
  if (!opentui?.SyntaxStyle) return undefined;
  try {
    return new opentui.SyntaxStyle({
      keyword: theme.accent,
      string: theme.success,
      number: theme.warning,
      comment: theme.textSubtle,
      function: theme.info,
      type: theme.reasoning,
      property: theme.user,
      operator: theme.text,
      punctuation: theme.textMuted,
    });
  } catch {
    return undefined;
  }
}

export function mockNode(options: BoxProps = {}): any {
  const children: any[] = [];
  let text = String(options.content ?? options.diff ?? options.value ?? "");
  let title = options.title as string | undefined;
  let placeholder = String(options.placeholder ?? "");
  let fg = options.fg;
  let bg = options.bg;
  let cursorOffset = 0;
  return {
    visible: options.visible ?? true,
    enableLayout: options.enableLayout ?? true,
    add(child: any) {
      children.push(child);
    },
    remove() {},
    children,
    get content() {
      return text;
    },
    set content(v: any) {
      text = String(v ?? "");
    },
    get diff() {
      return text;
    },
    set diff(v: any) {
      text = String(v ?? "");
    },
    get value() {
      return text;
    },
    set value(v: any) {
      text = String(v ?? "");
      cursorOffset = text.length;
    },
    get plainText() {
      return text;
    },
    get placeholder() {
      return placeholder;
    },
    set placeholder(v: any) {
      placeholder = String(v ?? "");
    },
    get title() {
      return title;
    },
    set title(v: string | undefined) {
      title = v;
    },
    get fg() {
      return fg;
    },
    set fg(v: any) {
      fg = v;
    },
    get bg() {
      return bg;
    },
    set bg(v: any) {
      bg = v;
    },
    get cursorOffset() {
      return cursorOffset;
    },
    set cursorOffset(v: number) {
      cursorOffset = Math.max(0, Math.min(text.length, Number.isFinite(v) ? v : text.length));
    },
    setText(v: string) {
      text = String(v ?? "");
      cursorOffset = text.length;
    },
    focus() {},
    blur() {},
    on() {},
    off() {},
  };
}
