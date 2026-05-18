type OpenTui = typeof import("@opentui/core");

export type RendererHost = {
  kind: "interactive" | "headless";
  ctx: any;
  root: any;
  width: number;
  height: number;
  requestRender: () => void;
  focus: (renderable: any) => void;
  blur: (renderable: any) => void;
  stop: () => void;
  on: (event: string, handler: (...args: any[]) => void) => void;
  off: (event: string, handler: (...args: any[]) => void) => void;
  // Forwarded to underlying renderer if available.
  opentui: OpenTui | null;
};

const isTty = (): boolean => Boolean(process.stdout.isTTY);

export async function createRendererHost(): Promise<RendererHost> {
  if (!isTty()) return headlessHost();
  const opentui = await import("@opentui/core").catch(() => null);
  if (!opentui?.createCliRenderer) return headlessHost();
  const mouseEnv = (process.env.TINYAGENT_TUI_MOUSE ?? "on").toLowerCase();
  const useMouse = mouseEnv !== "off" && mouseEnv !== "0" && mouseEnv !== "false";
  try {
    const renderer = await opentui.createCliRenderer({
      screenMode: "alternate-screen",
      exitOnCtrlC: false,
      targetFps: 60,
      maxFps: 120,
      useMouse,
      enableMouseMovement: useMouse,
      autoFocus: true,
      consoleMode: "disabled",
      gatherStats: false,
    });
    renderer.start?.();
    return {
      kind: "interactive",
      ctx: renderer,
      root: renderer.root,
      get width() {
        return renderer.width;
      },
      get height() {
        return renderer.height;
      },
      requestRender: () => renderer.requestRender?.(),
      focus: (r: any) => renderer.focusRenderable?.(r),
      blur: (r: any) => renderer.blurRenderable?.(r),
      stop: () => {
        renderer.stop?.();
        renderer.destroy?.();
      },
      on: (event: string, handler: (...args: any[]) => void) => {
        // "keypress" / "keyrelease" come from the KeyHandler, everything else from the renderer.
        if (event === "keypress" || event === "keyrelease") {
          (renderer as any).keyInput?.on?.(event, handler);
          return;
        }
        renderer.on?.(event, handler);
      },
      off: (event: string, handler: (...args: any[]) => void) => {
        if (event === "keypress" || event === "keyrelease") {
          (renderer as any).keyInput?.off?.(event, handler);
          return;
        }
        renderer.off?.(event, handler);
      },
      opentui,
    } as RendererHost;
  } catch {
    return headlessHost();
  }
}

function headlessHost(): RendererHost {
  const handlers: Map<string, Set<(...args: any[]) => void>> = new Map();
  return {
    kind: "headless",
    ctx: null,
    root: { add() {}, remove() {}, children: [] },
    width: 80,
    height: 24,
    requestRender: () => {},
    focus: () => {},
    blur: () => {},
    stop: () => {},
    on: (event, handler) => {
      const set = handlers.get(event) ?? new Set();
      set.add(handler);
      handlers.set(event, set);
    },
    off: (event, handler) => {
      handlers.get(event)?.delete(handler);
    },
    opentui: null,
  };
}
