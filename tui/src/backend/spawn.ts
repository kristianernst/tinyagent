import { existsSync } from "node:fs";
import { join } from "node:path";

type SpawnOptions = {
  workspace: string;
  provider: string;
  model?: string;
  profile?: string;
  approvalMode?: string;
  host?: string;
  debug?: number;
};

export type SpawnedBackend = {
  baseUrl: string;
  stop: () => void;
};

declare const Bun: {
  spawn: (args: string[], opts?: { stdout?: "pipe"; stderr?: "pipe" }) => {
    stdout: ReadableStream<Uint8Array>;
    stderr: ReadableStream<Uint8Array>;
    kill: () => void;
  };
};

export async function spawnBackend(options: SpawnOptions): Promise<SpawnedBackend> {
  const host = options.host ?? "127.0.0.1";
  const args = [
    ...backendCommand(),
    "serve",
    "--workspace",
    options.workspace,
    "--host",
    host,
    "--port",
    "0",
    "--print-json",
    "--provider",
    options.provider,
    "--stream",
    "--debug",
    String(options.debug ?? 1),
    "--approval-mode",
    options.approvalMode ?? "on-request",
  ];
  if (options.model) args.push("--model", options.model);
  if (options.profile) args.push("--profile", options.profile);
  const proc = Bun.spawn(args, { stdout: "pipe", stderr: "pipe" });
  const baseUrl = await readServerUrl(proc.stdout, host);
  return { baseUrl, stop: () => proc.kill() };
}

function backendCommand(): string[] {
  const override = process.env.TINYAGENT_TUI_PYTHON;
  if (override) return [override, "-m", "tinyagent.cli"];

  for (const candidate of [
    join(process.cwd(), ".venv", "bin", "python3"),
    join(process.cwd(), "..", ".venv", "bin", "python3"),
  ]) {
    if (existsSync(candidate)) return [candidate, "-m", "tinyagent.cli"];
  }

  return ["uv", "run", "python", "-m", "tinyagent.cli"];
}

export async function readServerUrl(stream: ReadableStream<Uint8Array>, host: string): Promise<string> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const serverUrl = parseServerUrl(buffer, host);
    if (serverUrl) return serverUrl;
  }
  throw new Error("tinyagent serve did not print a listening URL");
}

export function parseServerUrl(buffer: string, host: string): string | null {
  for (const line of buffer.split(/\r?\n/)) {
    if (!line.trim().startsWith("{")) continue;
    try {
      const payload = JSON.parse(line) as { url?: unknown };
      if (typeof payload.url === "string" && payload.url.startsWith("http://")) return payload.url;
    } catch {
      // Ignore partial or unrelated stdout and keep waiting for the server line.
    }
  }
  const match = buffer.match(/http:\/\/[^:\s]+:(\d+)/);
  return match ? `http://${host}:${match[1]}` : null;
}
