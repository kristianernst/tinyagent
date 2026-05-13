import { useEffect, useMemo, useRef } from "react";

const ORB_PALETTES: Record<string, string[]> = {
  ember: ["#07070a", "#3a0a08", "#9c1a10", "#e84818", "#ffa01c", "#ffe040", "#c8ff3c", "#3cf088", "#a8ffd8"],
  reef: ["#03060c", "#08203c", "#0e60a8", "#1cb4e8", "#54f0e0", "#a8ffd0", "#fff5b0", "#ffb850", "#ff5030"],
  cosmic: ["#06031a", "#1c0848", "#5418b8", "#a838e8", "#ff48c0", "#ff90a0", "#ffe080", "#a8f0ff", "#ffffff"],
  forest: ["#020a06", "#082818", "#147028", "#5cc830", "#c8ff48", "#fff5b0", "#f0a020", "#c44010", "#5c0810"],
  arctic: ["#020812", "#0a2c4c", "#2870a0", "#6cc0e0", "#c4f0f0", "#ffffff", "#e8c4ff", "#a040d8", "#48108c"],
  toxic: ["#020806", "#082018", "#0c5c2c", "#2cc848", "#c8ff20", "#ffffff", "#ff48c0", "#a01890", "#380838"],
};

const ORB_PALETTE_KEYS = Object.keys(ORB_PALETTES);
const BAYER4 = [
  [0, 8, 2, 10],
  [12, 4, 14, 6],
  [3, 11, 1, 9],
  [15, 7, 13, 5],
].map((row) => row.map((value) => (value + 0.5) / 16));

type RGB = [number, number, number];

type OrbParticle = {
  baseAng: number;
  baseRad: number;
  angSpeed: number;
  radFreq: number;
  radAmp: number;
  wobFreq: number;
  wobAmp: number;
  phase: number;
  phase2: number;
  r: number;
  rPhase: number;
  rFreq: number;
  from: number;
  to: number;
  morph: number;
  morphDur: number;
  x: number;
  y: number;
  rNow: number;
};

type OrbState = {
  seed: string;
  particles: OrbParticle[];
  t: number;
  colors: RGB[];
  particleColors: RGB[];
  bg: RGB;
  hot: RGB;
  hot2: RGB;
  embers: Array<{ x: number; y: number; life: number; hot: boolean }>;
};

const ORB_GRID = 22;
const ORB_PARTICLE_COUNT = 9;
const ORB_CONTRAST = 4;
const ORB_MORPH_RATE = 1;
const ORB_EMBER_RATE = 1.2;

function hexToRgb(value: string): RGB {
  const n = parseInt(value.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function lerpRgb(a: RGB, b: RGB, t: number): RGB {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
}

function makeSeededRandom(seed: string): () => number {
  let h = 0x811c9dc5;
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 0x01000193) >>> 0;
  return () => {
    h ^= h << 13;
    h >>>= 0;
    h ^= h >>> 17;
    h ^= h << 5;
    h >>>= 0;
    return h / 0xffffffff;
  };
}

function paletteFor(seed: string): string[] {
  const rand = makeSeededRandom(seed + ":palette");
  return ORB_PALETTES[ORB_PALETTE_KEYS[Math.floor(rand() * ORB_PALETTE_KEYS.length)]];
}

function initOrbState(seed: string, palette: string[]): OrbState {
  const rand = makeSeededRandom(seed + ":particles");
  const colors = palette.map(hexToRgb);
  const particleColors = colors.slice(1);
  const particles: OrbParticle[] = [];
  const colorCount = particleColors.length;

  for (let i = 0; i < ORB_PARTICLE_COUNT; i++) {
    const colorIndex = (i + ((rand() * colorCount) | 0)) % colorCount;
    particles.push({
      baseAng: (i / ORB_PARTICLE_COUNT) * Math.PI * 2,
      baseRad: ORB_GRID * (0.2 + rand() * 0.14),
      angSpeed: 0.18 + rand() * 0.22,
      radFreq: 0.25 + rand() * 0.35,
      radAmp: ORB_GRID * (0.06 + rand() * 0.07),
      wobFreq: 0.4 + rand() * 0.5,
      wobAmp: ORB_GRID * (0.04 + rand() * 0.06),
      phase: rand() * Math.PI * 2,
      phase2: rand() * Math.PI * 2,
      r: ORB_GRID * (0.2 + rand() * 0.1),
      rPhase: rand() * Math.PI * 2,
      rFreq: 0.2 + rand() * 0.3,
      from: colorIndex,
      to: (colorIndex + 1 + ((rand() * (colorCount - 2)) | 0)) % colorCount,
      morph: 0,
      morphDur: 1.6 + rand() * 1.6,
      x: ORB_GRID / 2,
      y: ORB_GRID / 2,
      rNow: ORB_GRID * 0.22,
    });
  }

  return {
    seed,
    particles,
    t: 0,
    colors,
    particleColors,
    bg: colors[0],
    hot: colors[colors.length - 1],
    hot2: colors[colors.length - 2],
    embers: [],
  };
}

export function AgentOrb({ seed, running, size = 18 }: { seed: string; running: boolean; size?: number }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stateRef = useRef<OrbState | null>(null);
  const stableSeed = seed || "tinyagent";
  const palette = useMemo(() => paletteFor(stableSeed), [stableSeed]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    if (!stateRef.current || stateRef.current.seed !== stableSeed) {
      stateRef.current = initOrbState(stableSeed, palette);
    }

    const img = ctx.createImageData(ORB_GRID, ORB_GRID);
    const data = img.data;
    const cx = ORB_GRID / 2;
    const cy = ORB_GRID / 2;
    const radius = ORB_GRID / 2 - 0.5;
    const radiusSq = radius * radius;
    let raf = 0;
    let last = 0;

    const tick = (now: number) => {
      if (!last) last = now;
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const state = stateRef.current;
      if (!state) {
        if (running) raf = requestAnimationFrame(tick);
        return;
      }

      state.t += dt;
      const t = state.t;
      const colorCount = state.particleColors.length;

      for (const particle of state.particles) {
        const ang = particle.baseAng + t * particle.angSpeed * ORB_MORPH_RATE + Math.sin(t * particle.wobFreq + particle.phase) * 0.35;
        const rad =
          particle.baseRad +
          Math.sin(t * particle.radFreq * ORB_MORPH_RATE + particle.phase) * particle.radAmp +
          Math.cos(t * particle.wobFreq * 0.6 + particle.phase2) * particle.wobAmp;
        particle.x = cx + Math.cos(ang) * rad;
        particle.y = cy + Math.sin(ang) * rad;
        particle.rNow = ORB_GRID * (0.22 + 0.06 * Math.sin(t * particle.rFreq + particle.rPhase));
        particle.morph += dt * ORB_MORPH_RATE;
        if (particle.morph >= particle.morphDur) {
          particle.from = particle.to;
          let next = (Math.random() * colorCount) | 0;
          let tries = 0;
          while (Math.abs(next - particle.from) < 2 && tries < 5) {
            next = (Math.random() * colorCount) | 0;
            tries++;
          }
          particle.to = next;
          particle.morph = 0;
          particle.morphDur = 1.4 + Math.random() * 1.8;
        }
      }

      const particleColors = state.particles.map((particle) => {
        const k = Math.min(1, particle.morph / particle.morphDur);
        return lerpRgb(state.particleColors[particle.from], state.particleColors[particle.to], k * k * (3 - 2 * k));
      });

      for (let i = state.embers.length - 1; i >= 0; i--) {
        state.embers[i].life -= dt * 5;
        if (state.embers[i].life <= 0) state.embers.splice(i, 1);
      }

      const spawnTarget = ORB_EMBER_RATE * dt * 60;
      const spawnCount = Math.floor(spawnTarget) + (Math.random() < spawnTarget % 1 ? 1 : 0);
      for (let i = 0; i < spawnCount; i++) {
        const particle = state.particles[(Math.random() * state.particles.length) | 0];
        const ang = Math.random() * Math.PI * 2;
        const rad = Math.random() * particle.rNow * 0.85;
        const x = Math.round(particle.x + Math.cos(ang) * rad);
        const y = Math.round(particle.y + Math.sin(ang) * rad);
        const dx = x - cx + 0.5;
        const dy = y - cy + 0.5;
        if (dx * dx + dy * dy < radiusSq && x >= 0 && x < ORB_GRID && y >= 0 && y < ORB_GRID) {
          state.embers.push({ x, y, life: 0.8 + Math.random() * 0.5, hot: Math.random() < 0.35 });
        }
      }

      let cursor = 0;
      for (let y = 0; y < ORB_GRID; y++) {
        for (let x = 0; x < ORB_GRID; x++) {
          const dx = x - cx + 0.5;
          const dy = y - cy + 0.5;
          if (dx * dx + dy * dy > radiusSq) {
            data[cursor++] = 0;
            data[cursor++] = 0;
            data[cursor++] = 0;
            data[cursor++] = 0;
            continue;
          }

          let bestW = 0;
          let bestI = -1;
          let secondW = 0;
          let secondI = -1;
          for (let i = 0; i < state.particles.length; i++) {
            const particle = state.particles[i];
            const px = x + 0.5 - particle.x;
            const py = y + 0.5 - particle.y;
            const w = Math.pow((particle.rNow * particle.rNow) / (px * px + py * py + 0.4), ORB_CONTRAST);
            if (w > bestW) {
              secondW = bestW;
              secondI = bestI;
              bestW = w;
              bestI = i;
            } else if (w > secondW) {
              secondW = w;
              secondI = i;
            }
          }

          let color = bestI < 0 ? state.bg : particleColors[bestI];
          if (bestI >= 0 && secondI >= 0 && secondW > 0) {
            const ratio = secondW / (bestW + secondW);
            color = ratio > BAYER4[y & 3][x & 3] * 0.55 ? particleColors[secondI] : color;
          }

          data[cursor++] = color[0];
          data[cursor++] = color[1];
          data[cursor++] = color[2];
          data[cursor++] = 255;
        }
      }

      for (const ember of state.embers) {
        if (ember.life <= 0.15) continue;
        const idx = (ember.y * ORB_GRID + ember.x) * 4;
        const color = ember.hot ? state.hot : state.hot2;
        data[idx] = color[0];
        data[idx + 1] = color[1];
        data[idx + 2] = color[2];
        data[idx + 3] = 255;
      }

      ctx.putImageData(img, 0, 0);
      if (running) raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => {
      if (raf) cancelAnimationFrame(raf);
    };
  }, [palette, running, stableSeed]);

  return (
    <span className="orb" style={{ width: size, height: size, background: palette[0] }} aria-hidden="true">
      <canvas ref={canvasRef} width={ORB_GRID} height={ORB_GRID} className="orb-canvas" />
    </span>
  );
}
