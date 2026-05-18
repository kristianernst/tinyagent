export type Renderer = {
  render: (content: string) => void;
  stop: () => void;
};

type OpenTuiModule = {
  createCliRenderer?: (options: Record<string, unknown>) => Promise<{
    start?: () => void;
    stop?: () => void;
    destroy?: () => void;
    requestRender?: () => void;
  }>;
};

export async function createRenderer(): Promise<Renderer> {
  if (!process.stdout.isTTY) return plainRenderer();
  const opentui = await import("@opentui/core").catch(() => null as OpenTuiModule | null);
  if (opentui?.createCliRenderer) {
    try {
      const renderer = await opentui.createCliRenderer({
        screenMode: "split-footer",
        footerHeight: 12,
        externalOutputMode: "capture-stdout",
        exitOnCtrlC: false,
        targetFps: 30,
        maxFps: 60,
        useMouse: true,
        consoleMode: "disabled",
      });
      renderer.start?.();
      return {
        render(content: string) {
          process.stdout.write(`${content}\n`);
          renderer.requestRender?.();
        },
        stop() {
          renderer.stop?.();
          renderer.destroy?.();
        },
      };
    } catch {
      return plainRenderer();
    }
  }
  return plainRenderer();
}

function plainRenderer(): Renderer {
  return {
    render(content: string) {
      process.stdout.write(`${content}\n`);
    },
    stop() {},
  };
}
