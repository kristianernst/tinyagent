import type { Theme } from "./theme";

export type BoxProps = Record<string, unknown>;

export function makeBox(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode();
  return new opentui.BoxRenderable(ctx, options);
}

export function makeText(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode();
  return new opentui.TextRenderable(ctx, options);
}

export function makeScrollBox(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode();
  return new opentui.ScrollBoxRenderable(ctx, options);
}

export function makeInput(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode();
  return new opentui.InputRenderable(ctx, options);
}

export function makeTextarea(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode();
  return new opentui.TextareaRenderable(ctx, options);
}

export function makeSelect(opentui: any, ctx: any, options: BoxProps): any {
  if (!opentui) return mockNode();
  return new opentui.SelectRenderable(ctx, options);
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

export function mockNode(): any {
  const children: any[] = [];
  return {
    add(child: any) {
      children.push(child);
    },
    remove() {},
    children,
    set content(_v: any) {},
    set diff(_v: any) {},
    set value(_v: any) {},
    focus() {},
    blur() {},
    on() {},
    off() {},
  };
}
