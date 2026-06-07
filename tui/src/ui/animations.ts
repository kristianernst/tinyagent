// Lightweight animations layer. Falls back to no-op when @opentui/core's
// animation engine is unavailable (e.g. headless tests).

import { motionMs } from "../design/primitives";

type Easing = "linear" | "inOutSine" | "outBack" | "outQuad" | "outBounce" | "outExpo";

export type AnimationHandle = {
  cancel: () => void;
};

export type Animator = {
  fadeIn: (node: any, opts?: { duration?: number; ease?: Easing; from?: number; to?: number }) => AnimationHandle;
  fadeOut: (node: any, opts?: { duration?: number; ease?: Easing; from?: number; to?: number }) => AnimationHandle;
  slideIn: (node: any, opts: { axis: "x" | "y"; from: number; to: number; duration?: number; ease?: Easing }) => AnimationHandle;
  pulse: (node: any, opts?: { duration?: number; ease?: Easing }) => AnimationHandle;
  cancelAll: () => void;
};

export function createAnimator(opentui: any | null): Animator {
  if (!opentui?.createTimeline) return noopAnimator();

  const timelines: any[] = [];
  const register = (tl: any) => {
    timelines.push(tl);
    tl.play?.();
    return { cancel: () => tl.pause?.() } satisfies AnimationHandle;
  };

  return {
    fadeIn(node, opts = {}) {
      if (!node || !("opacity" in node)) return noop();
      try {
        node.opacity = opts.from ?? 0;
        const tl = opentui.createTimeline({ autoplay: false });
        tl.add(node, {
          opacity: opts.to ?? 1,
          duration: opts.duration ?? motionMs.slow,
          ease: opts.ease ?? "outQuad",
        });
        return register(tl);
      } catch {
        node.opacity = opts.to ?? 1;
        return noop();
      }
    },
    fadeOut(node, opts = {}) {
      if (!node || !("opacity" in node)) return noop();
      try {
        const tl = opentui.createTimeline({ autoplay: false });
        tl.add(node, {
          opacity: opts.to ?? 0,
          duration: opts.duration ?? motionMs.slow,
          ease: opts.ease ?? "outQuad",
        });
        return register(tl);
      } catch {
        node.opacity = opts.to ?? 0;
        return noop();
      }
    },
    slideIn(node, opts) {
      if (!node) return noop();
      try {
        const prop = opts.axis === "x" ? "left" : "top";
        if (!(prop in node)) return noop();
        node[prop] = opts.from;
        const tl = opentui.createTimeline({ autoplay: false });
        tl.add(node, {
          [prop]: opts.to,
          duration: opts.duration ?? motionMs.slow,
          ease: opts.ease ?? "outBack",
        });
        return register(tl);
      } catch {
        return noop();
      }
    },
    pulse(node, opts = {}) {
      if (!node) return noop();
      try {
        const tl = opentui.createTimeline({ autoplay: false });
        tl.add(node, {
          opacity: 0.55,
          duration: opts.duration ?? motionMs.dwell,
          ease: opts.ease ?? "inOutSine",
          alternate: true,
          loop: true,
        });
        return register(tl);
      } catch {
        return noop();
      }
    },
    cancelAll() {
      for (const tl of timelines) tl.pause?.();
      timelines.length = 0;
    },
  };
}

function noopAnimator(): Animator {
  return {
    fadeIn: () => noop(),
    fadeOut: () => noop(),
    slideIn: () => noop(),
    pulse: () => noop(),
    cancelAll: () => {},
  };
}

function noop(): AnimationHandle {
  return { cancel: () => {} };
}
