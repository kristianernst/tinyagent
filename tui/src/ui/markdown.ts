// Minimal markdown-ish line wrapper used when @opentui/core's MarkdownRenderable
// is unavailable (e.g. headless tests). Keeps the rendered text readable.

export function plainMarkdown(input: string, width = 80): string {
  if (!input) return "";
  const lines: string[] = [];
  for (const raw of input.split("\n")) {
    if (raw.length <= width) {
      lines.push(raw);
      continue;
    }
    let rest = raw;
    while (rest.length > width) {
      const cut = rest.lastIndexOf(" ", width);
      const idx = cut > 0 ? cut : width;
      lines.push(rest.slice(0, idx));
      rest = rest.slice(idx).trimStart();
    }
    if (rest) lines.push(rest);
  }
  return lines.join("\n");
}
