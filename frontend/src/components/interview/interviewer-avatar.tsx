"use client";

import { useEffect, useRef, useState } from "react";

import {
  blendField,
  presenceCaption,
  presenceField,
  type PresenceField,
  type PresenceMood,
} from "@/components/interview/agent-audio";

type InterviewerPresenceProps = {
  level: number;
  mood?: PresenceMood;
};

type NerveNode = {
  x: number;
  y: number;
  z: number;
  r: number;
  phase: number;
};

type NerveEdge = {
  a: number;
  b: number;
  hue: number;
  gen: number;
  phase: number;
};

type NerveChain = {
  nodes: number[];
  hue: number;
  gen: number;
  phase: number;
};

type Pulse = {
  edge: number;
  t: number;
  hops: number;
};

type Point = {
  x: number;
  y: number;
  z: number;
  r: number;
};

const HUES: readonly (readonly [number, number, number])[] = [
  [124, 68, 255],
  [168, 85, 247],
  [192, 70, 230],
  [236, 64, 168],
  [255, 70, 150],
  [255, 120, 190],
  [70, 190, 255],
];

const NETWORK = growNetwork(0x51f7);

export function InterviewerPresence({ level, mood = "listening" }: InterviewerPresenceProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const levelRef = useRef(level);
  const moodRef = useRef(mood);
  const reducedRef = useRef(false);
  const shownRef = useRef<PresenceMood>(mood);
  const fieldRef = useRef<PresenceField>(presenceField(mood, 0, false));
  levelRef.current = level;
  moodRef.current = mood;
  const [reducedMotion, setReducedMotion] = useState(false);
  const [shown, setShown] = useState<PresenceMood>(mood);

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => {
      reducedRef.current = motion.matches;
      setReducedMotion(motion.matches);
    };
    apply();
    motion.addEventListener("change", apply);
    return () => motion.removeEventListener("change", apply);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const context = canvas.getContext("2d");
    if (!context) {
      return;
    }
    const surface: HTMLCanvasElement = canvas;
    const paint: CanvasRenderingContext2D = context;
    const pulses: Pulse[] = [];
    let frame = 0;
    let time = 0;
    let stop = false;
    let last = performance.now();

    function draw(now: number) {
      if (stop) {
        return;
      }
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      time += dt;
      const parent = surface.parentElement;
      const width = parent?.clientWidth ?? 640;
      const height = parent?.clientHeight ?? 480;
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      if (surface.width !== Math.floor(width * ratio) || surface.height !== Math.floor(height * ratio)) {
        surface.width = Math.floor(width * ratio);
        surface.height = Math.floor(height * ratio);
      }
      const target = presenceField(moodRef.current, levelRef.current, reducedRef.current, shownRef.current);
      const field = blendField(fieldRef.current, target, reducedRef.current ? 1 : Math.min(1, dt * 1.6));
      fieldRef.current = field;
      if (target.mood !== shownRef.current) {
        shownRef.current = target.mood;
        setShown(target.mood);
      }
      paint.setTransform(ratio, 0, 0, ratio, 0, 0);
      paint.globalCompositeOperation = "source-over";
      paint.fillStyle = "#050308";
      paint.fillRect(0, 0, width, height);
      const cx = width * 0.5;
      const cy = height * 0.46;
      const span = Math.max(width, height) * 0.7;
      const breath = 1 + Math.sin(time * (0.55 + field.breath)) * 0.035 * (reducedRef.current ? 0 : 1);
      const yaw = reducedRef.current ? 0.4 : time * (0.04 + field.drift * 0.025);
      const points = projectNetwork(NETWORK.nodes, cx, cy, span * breath, yaw, time, field.drift);
      const ordered = [...NETWORK.chains].sort((left, right) => chainDepth(left, points) - chainDepth(right, points));

      paint.lineCap = "round";
      paint.lineJoin = "round";
      for (const chain of ordered) {
        const fade = chainFade(chain, points, field.energy, field.gather);
        if (fade < 0.03) {
          continue;
        }
        const [red, green, blue] = HUES[chain.hue] ?? HUES[0];
        const widthScale = chain.gen <= 1 ? 0.85 : chain.gen >= 4 ? 0.4 : 0.55;
        strokeChain(paint, chain, points, time, field.drift);
        paint.strokeStyle = `rgba(${red}, ${green}, ${blue}, ${Math.min(0.16, fade * 0.28)})`;
        paint.lineWidth = widthScale * (1.15 + field.energy * 0.7);
        paint.stroke();
        paint.strokeStyle = `rgba(${red}, ${green}, ${blue}, ${fade})`;
        paint.lineWidth = widthScale * (0.32 + field.energy * 0.28);
        paint.stroke();
      }

      const core = Math.min(width, height) * (0.075 + Math.sin(time * 0.5) * 0.006 * field.breath);
      const veil = paint.createRadialGradient(cx, cy, core * 0.2, cx, cy, core * 2.4);
      veil.addColorStop(0, "rgba(3, 1, 8, 0.97)");
      veil.addColorStop(0.42, "rgba(8, 2, 16, 0.72)");
      veil.addColorStop(0.7, "rgba(28, 8, 36, 0.16)");
      veil.addColorStop(1, "rgba(0, 0, 0, 0)");
      paint.fillStyle = veil;
      paint.beginPath();
      paint.arc(cx, cy, core * 2.4, 0, Math.PI * 2);
      paint.fill();
      paint.fillStyle = "#04020a";
      paint.beginPath();
      irregularCore(paint, cx, cy, core * (0.85 + field.breath * 0.08), time);
      paint.fill();

      stepPulses(pulses, field, dt, reducedRef.current);
      paint.globalCompositeOperation = "lighter";
      for (const pulse of pulses) {
        const edge = NETWORK.edges[pulse.edge];
        const from = points[edge.a];
        const to = points[edge.b];
        const bend = Math.sin(time * 0.7 + edge.phase) * (4 + field.drift * 6);
        const control = controlPoint(from, to, bend);
        const at = quadratic(from, control, to, pulse.t);
        const [red, green, blue] = HUES[edge.hue];
        paint.beginPath();
        paint.arc(at.x, at.y, edge.gen < 3 ? 2.4 : 1.6, 0, Math.PI * 2);
        paint.fillStyle = `rgba(${red}, ${green}, ${blue}, 0.95)`;
        paint.shadowColor = `rgba(${red}, ${green}, ${blue}, 0.9)`;
        paint.shadowBlur = 14;
        paint.fill();
      }
      paint.shadowBlur = 0;
      paint.globalCompositeOperation = "source-over";

      const vignette = paint.createRadialGradient(cx, cy, span * 0.2, cx, cy, span * 0.72);
      vignette.addColorStop(0, "rgba(0, 0, 0, 0)");
      vignette.addColorStop(1, "rgba(0, 0, 0, 0.45)");
      paint.fillStyle = vignette;
      paint.fillRect(0, 0, width, height);

      if (!reducedRef.current) {
        frame = requestAnimationFrame(draw);
      }
    }

    frame = requestAnimationFrame(draw);
    return () => {
      stop = true;
      cancelAnimationFrame(frame);
    };
  }, [reducedMotion]);

  return (
    <div className="absolute inset-0 bg-[#050308]" role="img" aria-label={`Interviewer, ${shown}`}>
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
      <p className="pointer-events-none absolute left-8 top-[18%] text-[11px] font-semibold uppercase tracking-[0.32em] text-ivory/60">
        {presenceCaption(shown)}
      </p>
    </div>
  );
}

function growNetwork(seed: number): {
  nodes: NerveNode[];
  edges: NerveEdge[];
  outward: number[][];
  inward: number[][];
  chains: NerveChain[];
} {
  const rand = mulberry32(seed);
  const nodes: NerveNode[] = [];
  const edges: NerveEdge[] = [];
  const tips: { index: number; dx: number; dy: number; dz: number; gen: number }[] = [];

  for (let index = 0; index < 22; index += 1) {
    const dir = unit(rand() * 2 - 1, rand() * 2 - 1, rand() * 2 - 1);
    const radius = 0.035 + rand() * 0.05;
    nodes.push(place(dir.x * radius, dir.y * radius, dir.z * radius, rand));
    tips.push({ index: nodes.length - 1, dx: dir.x, dy: dir.y, dz: dir.z, gen: 0 });
  }

  let guard = 0;
  while (tips.length > 0 && nodes.length < 760 && guard < 8000) {
    guard += 1;
    const pick = Math.floor(rand() * tips.length);
    const tip = tips[pick];
    tips.splice(pick, 1);
    const origin = nodes[tip.index];
    if (!origin || origin.r > 1.08) {
      continue;
    }
    const turned = perturb(tip.dx, tip.dy, tip.dz, rand, tip.gen < 2 ? 0.7 : 1.15);
    const step = 0.016 + rand() * (0.02 + tip.gen * 0.006);
    const next = place(origin.x + turned.x * step, origin.y + turned.y * step, origin.z + turned.z * step, rand);
    if (next.r > 1.12 || next.r < origin.r * 0.9) {
      continue;
    }
    const index = nodes.length;
    nodes.push(next);
    edges.push({
      a: tip.index,
      b: index,
      hue: rand() < 0.1 ? HUES.length - 1 : Math.floor(rand() * (HUES.length - 1)),
      gen: tip.gen,
      phase: rand() * Math.PI * 2,
    });
    if (tip.gen < 11 && rand() > 0.06) {
      tips.push({ index, dx: turned.x, dy: turned.y, dz: turned.z, gen: tip.gen + 1 });
    }
    const branch = tip.gen < 2 ? 0.38 : 0.14;
    if (rand() < branch && nodes.length < 740) {
      const fork = perturb(turned.x, turned.y, turned.z, rand, 1.4);
      tips.push({ index, dx: fork.x, dy: fork.y, dz: fork.z, gen: tip.gen + 1 });
    }
  }

  for (let index = 0; index < nodes.length; index += 1) {
    const node = nodes[index];
    if (rand() > 0.22) {
      continue;
    }
    let nearest = -1;
    let best = 0.07;
    for (let other = index + 1; other < nodes.length; other += 1) {
      const gap = distance(node, nodes[other]);
      if (gap < best && Math.abs(node.r - nodes[other].r) < 0.16) {
        best = gap;
        nearest = other;
      }
    }
    if (nearest >= 0) {
      const inner = node.r <= nodes[nearest].r ? index : nearest;
      const outer = inner === index ? nearest : index;
      edges.push({
        a: inner,
        b: outer,
        hue: rand() < 0.14 ? HUES.length - 1 : Math.floor(rand() * (HUES.length - 1)),
        gen: 4,
        phase: rand() * Math.PI * 2,
      });
    }
  }

  const outward = nodes.map(() => [] as number[]);
  const inward = nodes.map(() => [] as number[]);
  edges.forEach((edge, index) => {
    outward[edge.a]?.push(index);
    inward[edge.b]?.push(index);
  });
  return { nodes, edges, outward, inward, chains: traceChains(nodes, edges, outward) };
}

function projectNetwork(
  nodes: NerveNode[],
  cx: number,
  cy: number,
  span: number,
  yaw: number,
  time: number,
  drift: number,
): Point[] {
  const cos = Math.cos(yaw);
  const sin = Math.sin(yaw);
  return nodes.map((node) => {
    const twitch = Math.sin(time * 0.8 + node.phase) * drift * 0.02;
    const x = node.x + twitch;
    const y = node.y + Math.cos(time * 0.6 + node.phase) * drift * 0.015;
    const z = node.z;
    const xr = x * cos - z * sin;
    const zr = x * sin + z * cos;
    const depth = 1.12 + zr * 0.38;
    return {
      x: cx + (xr * span) / depth,
      y: cy + (y * span * 0.9) / depth,
      z: zr,
      r: node.r,
    };
  });
}

function stepPulses(pulses: Pulse[], field: PresenceField, dt: number, reduced: boolean) {
  if (reduced) {
    pulses.length = 0;
    return;
  }
  const outward = field.flow >= 0;
  const speed = (0.18 + field.energy * 0.55) * (outward ? 1 : 0.72);
  for (let index = pulses.length - 1; index >= 0; index -= 1) {
    const pulse = pulses[index];
    pulse.t += (outward ? speed : -speed) * dt;
    const done = pulse.t >= 1 || pulse.t <= 0;
    if (!done) {
      continue;
    }
    const edge = NETWORK.edges[pulse.edge];
    const nextNode = pulse.t >= 1 ? edge.b : edge.a;
    const options = pulse.t >= 1 ? NETWORK.outward[nextNode] : NETWORK.inward[nextNode];
    pulses.splice(index, 1);
    if (!edge || !options || pulse.hops >= 4 || options.length === 0) {
      continue;
    }
    const chance = field.mood === "speaking" ? 0.72 : field.mood === "thinking" ? 0.58 : 0.28;
    if (Math.random() > chance * field.energy) {
      continue;
    }
    const edgeIndex = options[Math.floor(Math.random() * options.length)];
    pulses.push({ edge: edgeIndex, t: pulse.t >= 1 ? 0.02 : 0.98, hops: pulse.hops + 1 });
  }
  const cap = Math.round(2 + field.energy * (field.mood === "speaking" ? 20 : field.mood === "thinking" ? 12 : 6));
  if (pulses.length >= cap || Math.random() > field.energy * 0.35) {
    return;
  }
  const pool = NETWORK.edges
    .map((edge, index) => ({ index, edge }))
    .filter(({ edge }) => {
      const inner = NETWORK.nodes[edge.a]?.r ?? 1;
      if (field.gather > 0.6) {
        return inner < 0.38;
      }
      if (field.flow > 0.4) {
        return inner < 0.5;
      }
      if (field.flow < -0.5) {
        return inner > 0.28;
      }
      return inner > 0.2 && inner < 0.7;
    });
  if (pool.length === 0) {
    return;
  }
  const chosen = pool[Math.floor(Math.random() * pool.length)];
  pulses.push({ edge: chosen.index, t: outward ? 0.02 : 0.98, hops: 0 });
}

function traceChains(nodes: NerveNode[], edges: NerveEdge[], outward: number[][]): NerveChain[] {
  const incoming = nodes.map(() => 0);
  for (const edge of edges) {
    if (edge.gen < 4) {
      incoming[edge.b] += 1;
    }
  }
  const chains: NerveChain[] = [];
  const started = new Set<number>();

  function follow(edgeIndex: number, path: number[]) {
    if (started.has(edgeIndex)) {
      return;
    }
    started.add(edgeIndex);
    const edge = edges[edgeIndex];
    if (!edge || edge.gen >= 4) {
      return;
    }
    const next = path.concat(edge.b);
    const kids = (outward[edge.b] ?? []).filter((index) => (edges[index]?.gen ?? 4) < 4);
    if (kids.length !== 1 || next.length >= 16) {
      chains.push({ nodes: next, hue: edge.hue, gen: edge.gen, phase: edge.phase });
      for (const kid of kids) {
        follow(kid, [edge.b]);
      }
      return;
    }
    follow(kids[0], next);
  }

  edges.forEach((edge, index) => {
    if (edge.gen >= 4) {
      chains.push({ nodes: [edge.a, edge.b], hue: edge.hue, gen: 4, phase: edge.phase });
      return;
    }
    if ((incoming[edge.a] ?? 0) === 0) {
      follow(index, [edge.a]);
    }
  });
  return chains;
}

function chainDepth(chain: NerveChain, points: Point[]): number {
  const first = points[chain.nodes[0] ?? 0];
  const last = points[chain.nodes[chain.nodes.length - 1] ?? 0];
  return ((first?.z ?? 0) + (last?.z ?? 0)) * 0.5;
}

function chainFade(chain: NerveChain, points: Point[], energy: number, gather: number): number {
  const sample = points[chain.nodes[Math.floor(chain.nodes.length / 2)] ?? 0];
  const radius = sample?.r ?? 1;
  const intoCore = radius < 0.08 ? radius / 0.08 : 1;
  const intoDark = radius > 0.96 ? Math.max(0, 1 - (radius - 0.96) / 0.18) : 1;
  const near = gather > 0.6 && radius < 0.42 ? 0.22 : 0;
  const base = chain.gen <= 1 ? 0.5 : chain.gen >= 4 ? 0.2 : 0.34;
  return Math.max(0, Math.min(0.92, (base + energy * 0.4 + near) * intoCore * intoDark));
}

function strokeChain(
  paint: CanvasRenderingContext2D,
  chain: NerveChain,
  points: Point[],
  time: number,
  drift: number,
) {
  const placed = chain.nodes
    .map((index, step) => {
      const point = points[index];
      if (!point) {
        return null;
      }
      const sway = Math.sin(time * 0.65 + chain.phase + step * 0.55) * (3 + drift * 7);
      const dx = step === 0 ? 0 : point.x - (points[chain.nodes[step - 1] ?? index]?.x ?? point.x);
      const dy = step === 0 ? 0 : point.y - (points[chain.nodes[step - 1] ?? index]?.y ?? point.y);
      const length = Math.hypot(dx, dy) || 1;
      return { x: point.x + (-dy / length) * sway, y: point.y + (dx / length) * sway };
    })
    .filter((point): point is { x: number; y: number } => point !== null);
  paint.beginPath();
  const first = placed[0];
  if (!first) {
    return;
  }
  paint.moveTo(first.x, first.y);
  if (placed.length === 2) {
    const end = placed[1];
    const dx = end.x - first.x;
    const dy = end.y - first.y;
    const length = Math.hypot(dx, dy) || 1;
    const bend = Math.sin(chain.phase + time * 0.4) * (12 + drift * 18);
    paint.quadraticCurveTo(first.x + dx * 0.5 + (-dy / length) * bend, first.y + dy * 0.5 + (dx / length) * bend, end.x, end.y);
    return;
  }
  for (let index = 1; index < placed.length - 1; index += 1) {
    const current = placed[index];
    const after = placed[index + 1];
    if (!current || !after) {
      continue;
    }
    paint.quadraticCurveTo(current.x, current.y, (current.x + after.x) * 0.5, (current.y + after.y) * 0.5);
  }
  const last = placed[placed.length - 1];
  if (last) {
    paint.lineTo(last.x, last.y);
  }
}

function irregularCore(paint: CanvasRenderingContext2D, cx: number, cy: number, radius: number, time: number) {
  const steps = 11;
  for (let step = 0; step <= steps; step += 1) {
    const angle = (step / steps) * Math.PI * 2;
    const warp = 0.68 + 0.32 * Math.sin(angle * 3 + time * 0.3) * Math.cos(angle * 2);
    const x = cx + Math.cos(angle) * radius * warp;
    const y = cy + Math.sin(angle) * radius * warp * 0.9;
    if (step === 0) {
      paint.moveTo(x, y);
    } else {
      paint.lineTo(x, y);
    }
  }
  paint.closePath();
}

function controlPoint(from: Point, to: Point, bend: number): { x: number; y: number } {
  const mx = (from.x + to.x) * 0.5;
  const my = (from.y + to.y) * 0.5;
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  return { x: mx + (-dy / length) * bend, y: my + (dx / length) * bend };
}

function quadratic(from: Point, control: { x: number; y: number }, to: Point, t: number): { x: number; y: number } {
  const stay = 1 - t;
  return {
    x: stay * stay * from.x + 2 * stay * t * control.x + t * t * to.x,
    y: stay * stay * from.y + 2 * stay * t * control.y + t * t * to.y,
  };
}

function place(x: number, y: number, z: number, rand: () => number): NerveNode {
  return { x, y, z, r: Math.hypot(x, y, z), phase: rand() * Math.PI * 2 };
}

function unit(x: number, y: number, z: number): { x: number; y: number; z: number } {
  const length = Math.hypot(x, y, z) || 1;
  return { x: x / length, y: y / length, z: z / length };
}

function perturb(x: number, y: number, z: number, rand: () => number, amount: number) {
  return unit(x + (rand() - 0.5) * amount, y + (rand() - 0.5) * amount, z + (rand() - 0.5) * amount * 0.8);
}

function distance(left: NerveNode, right: NerveNode): number {
  return Math.hypot(left.x - right.x, left.y - right.y, left.z - right.z);
}

function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let next = state;
    next = Math.imul(next ^ (next >>> 15), next | 1);
    next ^= next + Math.imul(next ^ (next >>> 7), next | 61);
    return ((next ^ (next >>> 14)) >>> 0) / 4294967296;
  };
}
