// Boxed-text helpers. Default is rounded corners (`╭╮╰╯`) for content
// surfaces. Heavy corners (`┏┓┗┛`) are reserved for modals. Square corners
// (`┌┐└┘`) remain available but should not be reached for in new code.
//
// See DESIGN_TOKENS.md §2.3.

import { glyphs } from "./glyphs";

export type BorderStyle = "round" | "heavy" | "square";

export function frame(title: string, body: string, width = 80, style: BorderStyle = "round"): string {
  const c = glyphs.corner[style];
  const inner = Math.max(20, width - 2);
  const header = title ? ` ${title} ` : "";
  const top = `${c.tl}${header}${c.h.repeat(Math.max(0, inner - header.length))}${c.tr}`;
  const bottom = `${c.bl}${c.h.repeat(inner)}${c.br}`;
  const lines = body.split("\n").map((line) => `${c.v}${line.slice(0, inner).padEnd(inner, " ")}${c.v}`);
  return [top, ...lines, bottom].join("\n");
}
