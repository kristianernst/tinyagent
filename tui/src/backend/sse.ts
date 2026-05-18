import type { RunEvent } from "../protocol/events";

export function parseSseBlock(block: string): RunEvent | null {
  const dataLines: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  try {
    return JSON.parse(dataLines.join("\n")) as RunEvent;
  } catch {
    return null;
  }
}

export function parseSseChunk(buffer: string): { events: RunEvent[]; rest: string } {
  const events: RunEvent[] = [];
  let rest = buffer;
  let index = rest.indexOf("\n\n");
  while (index !== -1) {
    const block = rest.slice(0, index);
    rest = rest.slice(index + 2);
    const event = parseSseBlock(block);
    if (event) events.push(event);
    index = rest.indexOf("\n\n");
  }
  return { events, rest };
}

export async function readSse(
  response: Response,
  onEvent: (event: RunEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  if (!response.body) throw new Error("SSE response has no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (!signal?.aborted) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parsed = parseSseChunk(buffer);
    buffer = parsed.rest;
    for (const event of parsed.events) onEvent(event);
  }
}
