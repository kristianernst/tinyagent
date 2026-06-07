import { statSync } from "node:fs";
import { resolve, sep } from "node:path";
import type { WorkspaceFileMetadata } from "../state/reducer";

export function metadataForWorkspaceFiles(root: string | undefined, files: string[]): WorkspaceFileMetadata {
  if (!root) return {};
  const rootPath = resolve(root);
  const metadata: WorkspaceFileMetadata = {};
  for (const file of files) {
    const fullPath = resolve(rootPath, file);
    if (!isWithinRoot(rootPath, fullPath)) continue;
    try {
      const stat = statSync(fullPath);
      if (!stat.isFile()) continue;
      metadata[file] = { bytes: stat.size, mtimeMs: stat.mtimeMs };
    } catch {
      // Metadata is nice-to-have; remote or changing workspaces can race.
    }
  }
  return metadata;
}

function isWithinRoot(root: string, target: string): boolean {
  return target === root || target.startsWith(root.endsWith(sep) ? root : `${root}${sep}`);
}
