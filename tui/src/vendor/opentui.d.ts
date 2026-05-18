declare module "@opentui/core" {
  export function createCliRenderer(options: Record<string, unknown>): Promise<{
    start?: () => void;
    stop?: () => void;
    destroy?: () => void;
    requestRender?: () => void;
  }>;
}
