import { spawn } from "node:child_process";
import { platform } from "node:os";

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    const command = platform() === "darwin" ? "pbcopy" : platform() === "win32" ? "clip" : "xclip";
    const args = platform() === "linux" ? ["-selection", "clipboard"] : [];
    const child = spawn(command, args, { stdio: ["pipe", "ignore", "ignore"] });
    child.stdin?.write(text);
    child.stdin?.end();
    return await new Promise<boolean>((resolve) => {
      child.on("error", () => resolve(false));
      child.on("close", (code) => resolve(code === 0));
    });
  } catch {
    return false;
  }
}

export function copyLastAssistant(turns: Array<{ assistant?: string }> | undefined): Promise<boolean> {
  const last = [...(turns ?? [])].reverse().find((turn) => turn.assistant);
  if (!last?.assistant) return Promise.resolve(false);
  return copyToClipboard(last.assistant);
}
