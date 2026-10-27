export type FieldMode = "idle" | "listening" | "thinking" | "speaking";

export type FieldSignal = { voice: number; heard: number };

type Tint = 0 | 1 | 2;

type RegionSpec = {
  x: number;
  y: number;
  sx: number;
  sy: number;
  count: number;
  knots: number;
  reach: number;
  cap: number;
  jitter: number;
  pace: number;
  tint: Tint;
  hubs: number;
  hubReach: number;
  weight: number;
  input: boolean;
  scatter: boolean;
};

type Region = {
  spec: RegionSpec;
  cx: number;
  cy: number;
  wanderX: number;
  wanderY: number;
  wanderTX: number;
  wanderTY: number;
  wanderAt: number;
  knotX: Float32Array;
  knotY: Float32Array;
  knotTX: Float32Array;
  knotTY: Float32Array;
  reorgAt: number;
  phase: number;
};

type Link = { a: number; b: number; born: number; life: number; bend: number; carries: boolean };
type Loop = { members: number[]; born: number; life: number };
type Arrival = { x: number; y: number; target: number; speed: number };
type Pulse = { s: number; speed: number };

const TINTS: readonly (readonly [number, number, number])[] = [
  [62, 136, 255],
  [94, 84, 246],
  [146, 74, 232],
];

const REGIONS: readonly RegionSpec[] = [
  { x: 0.8, y: -0.06, sx: 0.28, sy: 0.36, count: 760, knots: 8, reach: 0.064, cap: 8, jitter: 0.009, pace: 2.6, tint: 2, hubs: 2, hubReach: 0.16, weight: 0.95, input: false, scatter: false },
  { x: 0.4, y: -0.47, sx: 0.22, sy: 0.11, count: 144, knots: 4, reach: 0.11, cap: 5, jitter: 0.007, pace: 1.5, tint: 2, hubs: 2, hubReach: 0.3, weight: 0.7, input: false, scatter: false },
  { x: 0.02, y: 0.02, sx: 0.42, sy: 0.12, count: 192, knots: 5, reach: 0.12, cap: 4, jitter: 0.006, pace: 1.1, tint: 1, hubs: 3, hubReach: 0.32, weight: 0.65, input: false, scatter: false },
  { x: -0.64, y: 0.1, sx: 0.3, sy: 0.25, count: 116, knots: 4, reach: 0.18, cap: 4, jitter: 0.005, pace: 0.7, tint: 0, hubs: 4, hubReach: 0.42, weight: 0.6, input: true, scatter: false },
  { x: -1.28, y: -0.3, sx: 0.2, sy: 0.18, count: 30, knots: 2, reach: 0.26, cap: 3, jitter: 0.004, pace: 0.5, tint: 0, hubs: 1, hubReach: 0.5, weight: 0.5, input: true, scatter: false },
  { x: 0.62, y: 0.54, sx: 0.32, sy: 0.06, count: 88, knots: 3, reach: 0.1, cap: 4, jitter: 0.006, pace: 1.2, tint: 1, hubs: 1, hubReach: 0.26, weight: 0.6, input: false, scatter: false },
  { x: 1.34, y: 0.26, sx: 0.12, sy: 0.24, count: 60, knots: 2, reach: 0.09, cap: 4, jitter: 0.008, pace: 1.7, tint: 2, hubs: 0, hubReach: 0, weight: 0.6, input: false, scatter: false },
  { x: 0, y: 0, sx: 1.6, sy: 0.9, count: 128, knots: 1, reach: 0.34, cap: 2, jitter: 0.004, pace: 0.4, tint: 1, hubs: 0, hubReach: 0, weight: 0.4, input: false, scatter: true },
];

const VIEW_W = 3.1;
const VIEW_H = 1.75;
const CELL = 0.1;
const GRID_X0 = -2;
const GRID_Y0 = -1.3;
const GRID_COLS = 40;
const GRID_ROWS = 26;
const LEVELS = 7;
const EDGE_ALPHA = 0.62;
const MAX_PAIRS = 16000;

export class NeuralField {
  mode: FieldMode = "idle";

  private time = 0;
  private tempo = 1;
  private voice = 0;
  private heard = 0;
  private speakingHold = 0;
  private heardHold = 0;
  private heardTotal = 0;
  private thinkingLeft = 0;

  private readonly count: number;
  private readonly regions: Region[];
  private readonly regionOf: Uint8Array;
  private readonly knotOf: Uint8Array;
  private readonly lx: Float32Array;
  private readonly ly: Float32Array;
  private readonly px: Float32Array;
  private readonly py: Float32Array;
  private readonly rx: Float32Array;
  private readonly ry: Float32Array;
  private readonly phase: Float32Array;
  private readonly heat: Float32Array;
  private readonly spark: Uint8Array;
  private readonly hubs: number[] = [];
  private readonly hubFlag: Uint8Array;
  private readonly degree: Uint8Array;
  private readonly gridHead = new Int32Array(GRID_COLS * GRID_ROWS);
  private readonly gridNext: Int32Array;
  private readonly pairA = new Int32Array(MAX_PAIRS);
  private readonly pairB = new Int32Array(MAX_PAIRS);
  private pairCount = 0;
  private readonly depth: Int16Array;
  private cascadeStart = -1;
  private cascadeDepth = 0;
  private cascadeSpeed = 34;
  private readonly buckets: number[][] = Array.from({ length: 3 * LEVELS }, () => []);
  private readonly hot: number[] = [];

  private links: Link[] = [];
  private loops: Loop[] = [];
  private arrivals: Arrival[] = [];
  private pulses: Pulse[] = [];
  private path: number[] = [];
  private pathFormedAt = 0;
  private pathPresence = 0;
  private pulseDebt = 0;
  private arrivalDebt = 0;
  private nextLink = 0.4;
  private nextLoop = 1.2;
  private nextCascade = 5;

  constructor(seed = 0x5f3a91) {
    const random = mulberry32(seed);
    const gauss = () => {
      const u = Math.max(1e-6, random());
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * random());
    };
    this.count = REGIONS.reduce((total, spec) => total + spec.count, 0);
    const n = this.count;
    this.regionOf = new Uint8Array(n);
    this.knotOf = new Uint8Array(n);
    this.lx = new Float32Array(n);
    this.ly = new Float32Array(n);
    this.px = new Float32Array(n);
    this.py = new Float32Array(n);
    this.rx = new Float32Array(n);
    this.ry = new Float32Array(n);
    this.phase = new Float32Array(n);
    this.heat = new Float32Array(n);
    this.spark = new Uint8Array(n);
    this.hubFlag = new Uint8Array(n);
    this.degree = new Uint8Array(n);
    this.gridNext = new Int32Array(n);
    this.depth = new Int16Array(n).fill(-1);

    this.regions = REGIONS.map((spec) => {
      const knotX = new Float32Array(spec.knots);
      const knotY = new Float32Array(spec.knots);
      for (let k = 0; k < spec.knots; k += 1) {
        knotX[k] = spec.scatter ? 0 : gauss() * spec.sx * 0.8;
        knotY[k] = spec.scatter ? 0 : gauss() * spec.sy * 0.8;
      }
      return {
        spec,
        cx: spec.x,
        cy: spec.y,
        wanderX: 0,
        wanderY: 0,
        wanderTX: 0,
        wanderTY: 0,
        wanderAt: 20 + random() * 30,
        knotX,
        knotY,
        knotTX: Float32Array.from(knotX),
        knotTY: Float32Array.from(knotY),
        reorgAt: 2 + random() * 6,
        phase: random() * Math.PI * 2,
      };
    });

    let index = 0;
    this.regions.forEach((region, regionIndex) => {
      const { spec } = region;
      const members: number[] = [];
      for (let m = 0; m < spec.count; m += 1) {
        const i = index;
        index += 1;
        members.push(i);
        this.regionOf[i] = regionIndex;
        this.knotOf[i] = Math.floor(random() * spec.knots);
        if (spec.scatter) {
          let x = 0;
          let y = 0;
          do {
            x = (random() - 0.42) * spec.sx * 2;
            y = (random() - 0.5) * spec.sy * 2;
          } while (x < -0.4 && y > 0.3);
          this.lx[i] = x;
          this.ly[i] = y;
        } else {
          this.lx[i] = gauss() * spec.sx * 0.95;
          this.ly[i] = gauss() * spec.sy * 0.95;
        }
        this.px[i] = spec.x + region.knotX[this.knotOf[i]] + this.lx[i];
        this.py[i] = spec.y + region.knotY[this.knotOf[i]] + this.ly[i];
        this.rx[i] = this.px[i];
        this.ry[i] = this.py[i];
        this.phase[i] = random() * Math.PI * 2;
        this.spark[i] = random() < 0.035 ? 1 : 0;
      }
      for (let h = 0; h < spec.hubs; h += 1) {
        const pick = members[Math.floor(random() * members.length)];
        if (pick !== undefined && !this.hubFlag[pick]) {
          this.hubFlag[pick] = 1;
          this.hubs.push(pick);
        }
      }
    });
  }

  step(dt: number, signal: FieldSignal) {
    this.time += dt;
    const t = this.time;
    this.voice += (signal.voice - this.voice) * Math.min(1, dt * (signal.voice > this.voice ? 18 : 5));
    this.heard += (signal.heard - this.heard) * Math.min(1, dt * (signal.heard > this.heard ? 14 : 4));

    this.speakingHold = signal.voice > 0.06 ? 0.7 : this.speakingHold - dt;
    if (signal.heard > 0.12) {
      this.heardHold = 1;
      this.heardTotal += dt;
    } else {
      this.heardHold -= dt;
    }
    let next: FieldMode;
    if (this.speakingHold > 0) {
      next = "speaking";
      this.thinkingLeft = 0;
      this.heardTotal = 0;
    } else if (this.heardHold > 0) {
      next = "listening";
    } else {
      if (this.heardTotal > 0.6) {
        this.thinkingLeft = 9;
        this.heardTotal = 0;
      }
      this.thinkingLeft -= dt;
      next = this.thinkingLeft > 0 ? "thinking" : "idle";
    }
    if (next === "speaking" && this.mode !== "speaking") {
      this.formPath();
    }
    if (next === "thinking" && this.mode !== "thinking") {
      for (const region of this.regions) {
        region.reorgAt = Math.min(region.reorgAt, t + Math.random() * 0.4);
      }
    }
    this.mode = next;

    const thinking = this.mode === "thinking";
    const tempoTarget = { idle: 1, listening: 1.25, thinking: 2.6, speaking: 1.45 }[this.mode];
    this.tempo += (tempoTarget - this.tempo) * Math.min(1, dt * 1.5);
    const tempo = this.tempo;
    const speaking = this.mode === "speaking";
    this.pathPresence += ((speaking ? 1 : 0) - this.pathPresence) * Math.min(1, dt * (speaking ? 3 : 0.7));

    for (const region of this.regions) {
      const { spec } = region;
      if (t > region.wanderAt) {
        region.wanderTX = (Math.random() - 0.5) * 0.28;
        region.wanderTY = (Math.random() - 0.5) * 0.2;
        region.wanderAt = t + 28 + Math.random() * 26;
      }
      region.wanderX += (region.wanderTX - region.wanderX) * Math.min(1, dt * 0.05);
      region.wanderY += (region.wanderTY - region.wanderY) * Math.min(1, dt * 0.05);
      region.cx = spec.x + region.wanderX + Math.sin(t * 0.033 + region.phase) * 0.06;
      region.cy = spec.y + region.wanderY + Math.cos(t * 0.029 + region.phase * 1.3) * 0.05;
      if (!spec.scatter && t > region.reorgAt) {
        const moves = thinking ? spec.knots : 1 + Math.floor(Math.random() * 2);
        for (let m = 0; m < moves; m += 1) {
          const k = Math.floor(Math.random() * spec.knots);
          region.knotTX[k] = gaussian() * spec.sx * 0.85;
          region.knotTY[k] = gaussian() * spec.sy * 0.85;
        }
        const interval = (5 + Math.random() * 7) / Math.sqrt(spec.pace);
        region.reorgAt = t + (thinking ? interval * 0.18 : interval);
      }
      const knotRate = Math.min(1, dt * 0.3 * Math.sqrt(spec.pace) * tempo);
      for (let k = 0; k < spec.knots; k += 1) {
        region.knotX[k] += (region.knotTX[k] - region.knotX[k]) * knotRate;
        region.knotY[k] += (region.knotTY[k] - region.knotY[k]) * knotRate;
      }
    }

    const decay = Math.exp(-3.2 * dt);
    const swap = dt * (thinking ? 0.14 : 0.012);
    for (let i = 0; i < this.count; i += 1) {
      const region = this.regions[this.regionOf[i]];
      const { spec } = region;
      if (!spec.scatter && Math.random() < swap) {
        this.knotOf[i] = Math.floor(Math.random() * spec.knots);
      }
      const k = this.knotOf[i];
      const tx = region.cx + region.knotX[k] + this.lx[i];
      const ty = region.cy + region.knotY[k] + this.ly[i];
      const follow = Math.min(1, dt * 0.9 * Math.sqrt(spec.pace) * tempo);
      this.px[i] += (tx - this.px[i]) * follow;
      this.py[i] += (ty - this.py[i]) * follow;
      const amp = spec.jitter * (thinking ? 1.8 : 1);
      const rate = spec.pace * tempo;
      const p = this.phase[i];
      this.rx[i] = this.px[i] + amp * (Math.sin(t * 1.7 * rate + p) + 0.5 * Math.sin(t * 4.1 * rate + p * 2.3));
      this.ry[i] = this.py[i] + amp * (Math.cos(t * 1.5 * rate + p * 1.7) + 0.5 * Math.cos(t * 3.7 * rate + p * 0.6));
      this.heat[i] *= decay;
    }

    this.stepCascade(t);
    this.stepLinks(t, dt);
    this.stepLoops(t);
    this.stepArrivals(dt);
    this.stepPulses(dt);
  }

  draw(pen: CanvasRenderingContext2D, width: number, height: number) {
    const scale = Math.min(width / VIEW_W, height / VIEW_H);
    const ox = width * 0.5;
    const oy = height * 0.5;
    const t = this.time;

    pen.globalCompositeOperation = "source-over";
    pen.fillStyle = "#000000";
    pen.fillRect(0, 0, width, height);
    pen.globalCompositeOperation = "lighter";

    for (const region of this.regions) {
      if (region.spec.scatter) {
        continue;
      }
      const [red, green, blue] = TINTS[region.spec.tint];
      const radius = Math.max(region.spec.sx, region.spec.sy) * 2.1 * scale;
      const cx = ox + region.cx * scale;
      const cy = oy + region.cy * scale;
      const density = Math.min(1, region.spec.count / 300);
      const haze = pen.createRadialGradient(cx, cy, 0, cx, cy, radius);
      haze.addColorStop(0, `rgba(${red}, ${green}, ${blue}, ${0.025 + density * 0.04})`);
      haze.addColorStop(1, "rgba(0, 0, 0, 0)");
      pen.fillStyle = haze;
      pen.fillRect(cx - radius, cy - radius, radius * 2, radius * 2);
    }

    this.collectEdges();
    pen.lineCap = "round";
    pen.lineWidth = 0.55;
    for (let tint = 0; tint < 3; tint += 1) {
      const [red, green, blue] = TINTS[tint];
      for (let level = 0; level < LEVELS; level += 1) {
        const segments = this.buckets[tint * LEVELS + level];
        if (segments.length === 0) {
          continue;
        }
        pen.beginPath();
        for (let s = 0; s < segments.length; s += 4) {
          pen.moveTo(ox + segments[s] * scale, oy + segments[s + 1] * scale);
          pen.lineTo(ox + segments[s + 2] * scale, oy + segments[s + 3] * scale);
        }
        pen.strokeStyle = `rgba(${red}, ${green}, ${blue}, ${((level + 0.5) / LEVELS) * EDGE_ALPHA})`;
        pen.stroke();
      }
    }

    for (const link of this.links) {
      const age = (t - link.born) / link.life;
      const envelope = Math.pow(Math.sin(Math.PI * Math.min(1, Math.max(0, age))), 0.8);
      const ax = ox + this.rx[link.a] * scale;
      const ay = oy + this.ry[link.a] * scale;
      const bx = ox + this.rx[link.b] * scale;
      const by = oy + this.ry[link.b] * scale;
      const mx = (ax + bx) / 2 - (by - ay) * link.bend;
      const my = (ay + by) / 2 + (bx - ax) * link.bend;
      const [red, green, blue] = TINTS[this.regions[this.regionOf[link.a]].spec.tint];
      const lift = Math.max(this.heat[link.a], this.heat[link.b]);
      pen.beginPath();
      pen.moveTo(ax, ay);
      pen.quadraticCurveTo(mx, my, bx, by);
      pen.strokeStyle = `rgba(${red}, ${green}, ${blue}, ${envelope * (0.2 + lift * 0.4)})`;
      pen.lineWidth = 0.5;
      pen.stroke();
      if (link.carries) {
        const u = (age * 1.7) % 1;
        const x = (1 - u) * (1 - u) * ax + 2 * (1 - u) * u * mx + u * u * bx;
        const y = (1 - u) * (1 - u) * ay + 2 * (1 - u) * u * my + u * u * by;
        pen.fillStyle = `rgba(225, 232, 255, ${envelope * 0.75})`;
        pen.fillRect(x - 0.7, y - 0.7, 1.4, 1.4);
      }
    }

    for (const loop of this.loops) {
      const age = (t - loop.born) / loop.life;
      const envelope = Math.sin(Math.PI * Math.min(1, Math.max(0, age)));
      const members = loop.members;
      const [red, green, blue] = TINTS[this.regions[this.regionOf[members[0]]].spec.tint];
      pen.beginPath();
      members.forEach((member, order) => {
        const x = ox + this.rx[member] * scale;
        const y = oy + this.ry[member] * scale;
        if (order === 0) {
          pen.moveTo(x, y);
        } else {
          pen.lineTo(x, y);
        }
      });
      pen.closePath();
      pen.strokeStyle = `rgba(${red}, ${green}, ${blue}, ${envelope * 0.38})`;
      pen.lineWidth = 0.55;
      pen.stroke();
      pen.beginPath();
      for (let m = 0; m < members.length; m += 1) {
        const from = members[m];
        const to = members[(m + 2) % members.length];
        pen.moveTo(ox + this.rx[from] * scale, oy + this.ry[from] * scale);
        pen.lineTo(ox + this.rx[to] * scale, oy + this.ry[to] * scale);
      }
      pen.strokeStyle = `rgba(${red}, ${green}, ${blue}, ${envelope * 0.16})`;
      pen.stroke();
    }

    for (let h = 0; h < this.hot.length; h += 3) {
      const a = this.hot[h];
      const b = this.hot[h + 1];
      const lift = this.hot[h + 2];
      const [red, green, blue] = TINTS[this.regions[this.regionOf[a]].spec.tint];
      const mix = (base: number) => Math.round(base + (240 - base) * lift * lift * 0.8);
      pen.beginPath();
      pen.moveTo(ox + this.rx[a] * scale, oy + this.ry[a] * scale);
      pen.lineTo(ox + this.rx[b] * scale, oy + this.ry[b] * scale);
      pen.strokeStyle = `rgba(${mix(red)}, ${mix(green)}, ${mix(blue)}, ${0.15 + lift * 0.6})`;
      pen.lineWidth = 0.55 + lift * 0.3;
      pen.stroke();
    }

    this.drawPath(pen, ox, oy, scale);

    for (const arrival of this.arrivals) {
      const tx = this.rx[arrival.target];
      const ty = this.ry[arrival.target];
      const dx = tx - arrival.x;
      const dy = ty - arrival.y;
      const length = Math.hypot(dx, dy) || 1;
      const x = ox + arrival.x * scale;
      const y = oy + arrival.y * scale;
      pen.beginPath();
      pen.moveTo(x - (dx / length) * 0.06 * scale, y - (dy / length) * 0.06 * scale);
      pen.lineTo(x, y);
      pen.strokeStyle = "rgba(140, 190, 255, 0.45)";
      pen.lineWidth = 0.6;
      pen.stroke();
      pen.fillStyle = "rgba(230, 240, 255, 0.8)";
      pen.fillRect(x - 0.7, y - 0.7, 1.4, 1.4);
    }

    this.drawNodes(pen, ox, oy, scale);
  }

  private collectEdges() {
    for (const bucket of this.buckets) {
      bucket.length = 0;
    }
    this.hot.length = 0;
    this.pairCount = 0;
    this.gridHead.fill(-1);
    this.degree.fill(0);
    const n = this.count;
    for (let i = 0; i < n; i += 1) {
      const cell = this.cellOf(this.rx[i], this.ry[i]);
      this.gridNext[i] = this.gridHead[cell];
      this.gridHead[cell] = i;
    }
    const t = this.time;
    const listening = this.heard;
    const tempo = this.tempo;
    for (let i = 0; i < n; i += 1) {
      const specI = this.regions[this.regionOf[i]].spec;
      const reachI = specI.reach * (specI.input ? 1 + listening * 0.6 : 1);
      const range = Math.ceil(reachI / CELL);
      const col = Math.min(GRID_COLS - 1, Math.max(0, Math.floor((this.rx[i] - GRID_X0) / CELL)));
      const row = Math.min(GRID_ROWS - 1, Math.max(0, Math.floor((this.ry[i] - GRID_Y0) / CELL)));
      for (let r = Math.max(0, row - range); r <= Math.min(GRID_ROWS - 1, row + range); r += 1) {
        for (let c = Math.max(0, col - range); c <= Math.min(GRID_COLS - 1, col + range); c += 1) {
          for (let j = this.gridHead[r * GRID_COLS + c]; j !== -1; j = this.gridNext[j]) {
            if (j <= i) {
              continue;
            }
            const specJ = this.regions[this.regionOf[j]].spec;
            if (this.degree[i] >= specI.cap) {
              break;
            }
            if (this.degree[j] >= specJ.cap) {
              continue;
            }
            const dx = this.rx[j] - this.rx[i];
            const dy = this.ry[j] - this.ry[i];
            const reachJ = specJ.reach * (specJ.input ? 1 + listening * 0.6 : 1);
            const reach = (reachI + reachJ) * 0.5;
            const d2 = dx * dx + dy * dy;
            if (d2 > reach * reach) {
              continue;
            }
            const hash = pairHash(i, j);
            const pace = (specI.pace + specJ.pace) * 0.5;
            const wave = Math.sin(t * (0.25 + hash * 1.1) * pace * tempo + hash * 40);
            const visible = Math.min(1, Math.max(0, (wave + 0.25) / 0.6));
            if (visible <= 0.02) {
              continue;
            }
            this.degree[i] += 1;
            this.degree[j] += 1;
            this.recordPair(i, j);
            const closeness = 1 - Math.sqrt(d2) / reach;
            const weight = (specI.weight + specJ.weight) * 0.5;
            this.pushEdge(i, j, (0.12 + 0.75 * closeness) * visible * weight, specI.tint);
          }
        }
      }
    }

    for (const hub of this.hubs) {
      const spec = this.regions[this.regionOf[hub]].spec;
      const reach = spec.hubReach * (spec.input ? 1 + listening * 0.4 : 1);
      for (let j = 0; j < n; j += 1) {
        if (j === hub) {
          continue;
        }
        const dx = this.rx[j] - this.rx[hub];
        const dy = this.ry[j] - this.ry[hub];
        const d2 = dx * dx + dy * dy;
        if (d2 > reach * reach) {
          continue;
        }
        const hash = pairHash(hub, j);
        const wave = Math.sin(t * (0.15 + hash * 0.5) * tempo + hash * 30);
        if (wave < -0.45) {
          continue;
        }
        const fall = Math.pow(1 - Math.sqrt(d2) / reach, 1.4);
        this.pushEdge(hub, j, fall * 0.5 * Math.min(1, (wave + 0.45) / 0.4), spec.tint);
      }
    }
  }

  private pushEdge(a: number, b: number, alpha: number, tint: Tint) {
    const lift = Math.min(this.heat[a], this.heat[b]);
    if (lift > 0.12) {
      this.hot.push(a, b, lift);
      return;
    }
    if (alpha < 0.02) {
      return;
    }
    const level = Math.min(LEVELS - 1, Math.floor((alpha / EDGE_ALPHA) * LEVELS));
    this.buckets[tint * LEVELS + level].push(this.rx[a], this.ry[a], this.rx[b], this.ry[b]);
  }

  private recordPair(a: number, b: number) {
    if (this.pairCount < MAX_PAIRS) {
      this.pairA[this.pairCount] = a;
      this.pairB[this.pairCount] = b;
      this.pairCount += 1;
    }
  }

  private cellOf(x: number, y: number): number {
    const col = Math.min(GRID_COLS - 1, Math.max(0, Math.floor((x - GRID_X0) / CELL)));
    const row = Math.min(GRID_ROWS - 1, Math.max(0, Math.floor((y - GRID_Y0) / CELL)));
    return row * GRID_COLS + col;
  }

  private stepCascade(t: number) {
    if (this.cascadeStart >= 0) {
      const front = (t - this.cascadeStart) * this.cascadeSpeed;
      for (let i = 0; i < this.count; i += 1) {
        const depth = this.depth[i];
        if (depth < 0) {
          continue;
        }
        const behind = front - depth;
        if (behind >= 0 && behind < 2.4) {
          this.heat[i] = Math.max(this.heat[i], 1 - behind / 2.4);
        }
      }
      if (front > this.cascadeDepth + 3) {
        this.cascadeStart = -1;
      }
      return;
    }
    if (t < this.nextCascade || this.pairCount === 0) {
      return;
    }
    let origin: number;
    if (this.mode === "speaking" && this.path.length > 0) {
      origin = this.path[Math.floor(Math.random() * this.path.length)];
    } else if (this.mode === "listening") {
      origin = this.randomIn((spec) => spec.input);
    } else {
      origin = Math.random() < 0.5 ? this.hubs[Math.floor(Math.random() * this.hubs.length)] : Math.floor(Math.random() * this.count);
    }
    this.launchCascade(origin, t);
    const wait = {
      idle: 7 + Math.random() * 7,
      listening: 4 + Math.random() * 3,
      thinking: 1.1 + Math.random() * 1.4,
      speaking: 5 + Math.random() * 4,
    }[this.mode];
    this.nextCascade = t + wait;
  }

  private launchCascade(origin: number, t: number) {
    const n = this.count;
    const offsets = new Int32Array(n + 1);
    for (let p = 0; p < this.pairCount; p += 1) {
      offsets[this.pairA[p] + 1] += 1;
      offsets[this.pairB[p] + 1] += 1;
    }
    for (let i = 0; i < n; i += 1) {
      offsets[i + 1] += offsets[i];
    }
    const fill = offsets.slice(0, n);
    const adjacency = new Int32Array(offsets[n]);
    for (let p = 0; p < this.pairCount; p += 1) {
      const a = this.pairA[p];
      const b = this.pairB[p];
      adjacency[fill[a]] = b;
      fill[a] += 1;
      adjacency[fill[b]] = a;
      fill[b] += 1;
    }
    this.depth.fill(-1);
    const queue = new Int32Array(n);
    let head = 0;
    let tail = 0;
    queue[tail] = origin;
    tail += 1;
    this.depth[origin] = 0;
    let deepest = 0;
    while (head < tail) {
      const node = queue[head];
      head += 1;
      const depth = this.depth[node];
      if (depth >= 42) {
        continue;
      }
      for (let e = offsets[node]; e < offsets[node + 1]; e += 1) {
        const next = adjacency[e];
        if (this.depth[next] === -1) {
          this.depth[next] = depth + 1;
          deepest = Math.max(deepest, depth + 1);
          queue[tail] = next;
          tail += 1;
        }
      }
    }
    this.cascadeDepth = deepest;
    this.cascadeSpeed = 18 + Math.random() * 12;
    this.cascadeStart = t;
  }

  private stepLinks(t: number, _dt: number) {
    this.links = this.links.filter((link) => t - link.born < link.life);
    const limit = this.mode === "thinking" ? 26 : 15;
    if (t < this.nextLink || this.links.length >= limit) {
      return;
    }
    const a = Math.floor(Math.random() * this.count);
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const b = Math.floor(Math.random() * this.count);
      const distance = Math.hypot(this.rx[a] - this.rx[b], this.ry[a] - this.ry[b]);
      if (this.regionOf[a] !== this.regionOf[b] && distance > 0.55) {
        this.addLink(a, b, t);
        break;
      }
    }
    const wait = { idle: 0.6 + Math.random() * 0.8, listening: 0.45, thinking: 0.18, speaking: 0.5 }[this.mode];
    this.nextLink = t + wait;
  }

  private addLink(a: number, b: number, t: number) {
    const thinking = this.mode === "thinking";
    this.links.push({
      a,
      b,
      born: t,
      life: thinking ? 1 + Math.random() * 1.5 : 2.5 + Math.random() * 4,
      bend: (Math.random() - 0.5) * 0.3,
      carries: Math.random() < 0.3,
    });
  }

  private stepLoops(t: number) {
    this.loops = this.loops.filter((loop) => t - loop.born < loop.life);
    const thinking = this.mode === "thinking";
    if (t < this.nextLoop || this.loops.length >= (thinking ? 12 : 6)) {
      return;
    }
    this.nextLoop = t + (thinking ? 0.4 : 1.2 + Math.random() * 1.2);
    const seed = this.randomIn((spec) => !spec.scatter && !spec.input);
    const size = 5 + Math.floor(Math.random() * 4);
    const nearest: { id: number; d: number }[] = [];
    for (let j = 0; j < this.count; j += 1) {
      if (j === seed) {
        continue;
      }
      const d = (this.rx[j] - this.rx[seed]) ** 2 + (this.ry[j] - this.ry[seed]) ** 2;
      if (d > 0.0004 && d < 0.06) {
        nearest.push({ id: j, d });
      }
    }
    nearest.sort((left, right) => left.d - right.d);
    const picked = [seed, ...nearest.slice(0, size - 1).map((entry) => entry.id)];
    if (picked.length < 4) {
      return;
    }
    const cx = picked.reduce((sum, id) => sum + this.rx[id], 0) / picked.length;
    const cy = picked.reduce((sum, id) => sum + this.ry[id], 0) / picked.length;
    picked.sort((left, right) => Math.atan2(this.ry[left] - cy, this.rx[left] - cx) - Math.atan2(this.ry[right] - cy, this.rx[right] - cx));
    this.loops.push({ members: picked, born: t, life: thinking ? 1.2 + Math.random() : 2 + Math.random() * 2.5 });
  }

  private stepArrivals(dt: number) {
    if (this.heard > 0.08) {
      this.arrivalDebt += dt * this.heard * 16;
      while (this.arrivalDebt >= 1) {
        this.arrivalDebt -= 1;
        this.arrivals.push({
          x: -VIEW_W / 2 - 0.08,
          y: (Math.random() - 0.5) * 1.1,
          target: this.randomIn((spec) => spec.input),
          speed: 0.9 + Math.random() * 0.6,
        });
      }
    } else {
      this.arrivalDebt = 0;
    }
    const t = this.time;
    this.arrivals = this.arrivals.filter((arrival) => {
      const dx = this.rx[arrival.target] - arrival.x;
      const dy = this.ry[arrival.target] - arrival.y;
      const distance = Math.hypot(dx, dy);
      if (distance < 0.03) {
        this.heat[arrival.target] = Math.max(this.heat[arrival.target], 0.85);
        if (Math.random() < 0.5) {
          this.addLink(arrival.target, this.randomIn((spec) => !spec.input && !spec.scatter), t);
        }
        return false;
      }
      const move = Math.min(distance, arrival.speed * dt);
      arrival.x += (dx / distance) * move;
      arrival.y += (dy / distance) * move;
      return true;
    });
  }

  private formPath() {
    const candidates = [...this.hubs].sort((left, right) => this.rx[left] - this.rx[right]);
    const waypoints: number[] = [];
    let lastX = -Infinity;
    for (const hub of candidates) {
      if (this.rx[hub] > lastX + 0.22 && (waypoints.length === 0 || Math.random() < 0.8)) {
        waypoints.push(hub);
        lastX = this.rx[hub];
      }
    }
    const coreHub = this.hubs.find((hub) => this.regionOf[hub] === 0);
    if (coreHub !== undefined && waypoints[waypoints.length - 1] !== coreHub) {
      waypoints.push(coreHub);
    }
    const used = new Set<number>(waypoints);
    const path: number[] = [];
    for (let w = 0; w < waypoints.length; w += 1) {
      const from = waypoints[w];
      path.push(from);
      const to = waypoints[w + 1];
      if (to === undefined) {
        continue;
      }
      const dx = this.rx[to] - this.rx[from];
      const dy = this.ry[to] - this.ry[from];
      const steps = Math.max(1, Math.min(4, Math.round(Math.hypot(dx, dy) / 0.12)));
      for (let s = 1; s <= steps; s += 1) {
        const u = s / (steps + 1);
        const wobble = (Math.random() - 0.5) * 0.08;
        const x = this.rx[from] + dx * u - dy * wobble;
        const y = this.ry[from] + dy * u + dx * wobble;
        let best = -1;
        let bestD = Infinity;
        for (let j = 0; j < this.count; j += 1) {
          if (used.has(j)) {
            continue;
          }
          const d = (this.rx[j] - x) ** 2 + (this.ry[j] - y) ** 2;
          if (d < bestD) {
            bestD = d;
            best = j;
          }
        }
        if (best >= 0 && bestD < 0.012) {
          used.add(best);
          path.push(best);
        }
      }
    }
    this.path = path;
    this.pathFormedAt = this.time;
    this.pulses = [];
  }

  private stepPulses(dt: number) {
    if (this.path.length < 2) {
      return;
    }
    if (this.mode === "speaking" && this.voice > 0.08) {
      this.pulseDebt += dt * (1.5 + this.voice * 8);
      while (this.pulseDebt >= 1) {
        this.pulseDebt -= 1;
        this.pulses.push({ s: 0, speed: 8 + this.voice * 10 + Math.random() * 4 });
      }
    }
    const last = this.path.length - 1;
    this.pulses = this.pulses.filter((pulse) => {
      pulse.s += pulse.speed * dt;
      const node = this.path[Math.min(last, Math.floor(pulse.s))];
      this.heat[node] = Math.max(this.heat[node], 0.5);
      return pulse.s < last;
    });
    const grown = Math.min(1, (this.time - this.pathFormedAt) / 0.8) * last;
    for (let p = 0; p <= Math.floor(grown); p += 1) {
      this.heat[this.path[p]] = Math.max(this.heat[this.path[p]], 0.1 * this.pathPresence);
    }
  }

  private drawPath(pen: CanvasRenderingContext2D, ox: number, oy: number, scale: number) {
    if (this.path.length < 2 || this.pathPresence < 0.02) {
      return;
    }
    const last = this.path.length - 1;
    const grown = Math.min(1, (this.time - this.pathFormedAt) / 0.8) * last;
    const point = (s: number): [number, number] => {
      const index = Math.min(last - 1, Math.floor(s));
      const u = Math.min(1, s - index);
      const a = this.path[index];
      const b = this.path[index + 1];
      return [
        ox + (this.rx[a] + (this.rx[b] - this.rx[a]) * u) * scale,
        oy + (this.ry[a] + (this.ry[b] - this.ry[a]) * u) * scale,
      ];
    };
    const trace = () => {
      pen.beginPath();
      const [x0, y0] = point(0);
      pen.moveTo(x0, y0);
      for (let s = 1; s <= Math.floor(grown); s += 1) {
        const [x, y] = point(s);
        pen.lineTo(x, y);
      }
      if (grown % 1 > 0) {
        const [x, y] = point(grown);
        pen.lineTo(x, y);
      }
    };
    const presence = this.pathPresence;
    trace();
    pen.strokeStyle = `rgba(150, 110, 255, ${presence * (0.05 + this.voice * 0.08)})`;
    pen.lineWidth = 3.5;
    pen.stroke();
    trace();
    pen.strokeStyle = `rgba(200, 185, 255, ${presence * (0.3 + this.voice * 0.45)})`;
    pen.lineWidth = 0.8;
    pen.stroke();

    for (const pulse of this.pulses) {
      if (pulse.s > grown) {
        continue;
      }
      const [hx, hy] = point(pulse.s);
      const [tx, ty] = point(Math.max(0, pulse.s - 1.4));
      const tail = pen.createLinearGradient(tx, ty, hx, hy);
      tail.addColorStop(0, "rgba(160, 140, 255, 0)");
      tail.addColorStop(1, `rgba(240, 244, 255, ${0.85 * presence})`);
      pen.beginPath();
      pen.moveTo(tx, ty);
      pen.lineTo(hx, hy);
      pen.strokeStyle = tail;
      pen.lineWidth = 1.1;
      pen.stroke();
      const glow = pen.createRadialGradient(hx, hy, 0, hx, hy, 7);
      glow.addColorStop(0, `rgba(190, 170, 255, ${0.35 * presence})`);
      glow.addColorStop(1, "rgba(0, 0, 0, 0)");
      pen.fillStyle = glow;
      pen.fillRect(hx - 7, hy - 7, 14, 14);
      pen.fillStyle = `rgba(255, 255, 255, ${0.95 * presence})`;
      pen.beginPath();
      pen.arc(hx, hy, 1.3, 0, Math.PI * 2);
      pen.fill();
    }
  }

  private drawNodes(pen: CanvasRenderingContext2D, ox: number, oy: number, scale: number) {
    const t = this.time;
    for (let tint = 0; tint < 3; tint += 1) {
      const [red, green, blue] = TINTS[tint];
      for (let band = 0; band < 3; band += 1) {
        pen.beginPath();
        let any = false;
        for (let i = 0; i < this.count; i += 1) {
          const spec = this.regions[this.regionOf[i]].spec;
          if (spec.tint !== tint || this.hubFlag[i] || this.heat[i] > 0.3) {
            continue;
          }
          const twinkle = 0.5 + 0.5 * Math.sin(t * (1.3 + spec.pace) + this.phase[i] * 3);
          if (Math.min(2, Math.floor(twinkle * 3)) !== band) {
            continue;
          }
          const size = 1.35;
          pen.rect(ox + this.rx[i] * scale - size / 2, oy + this.ry[i] * scale - size / 2, size, size);
          any = true;
        }
        if (any) {
          pen.fillStyle = `rgba(${Math.min(255, red + 50)}, ${Math.min(255, green + 50)}, ${Math.min(255, blue + 30)}, ${0.3 + band * 0.22})`;
          pen.fill();
        }
      }
    }

    for (let i = 0; i < this.count; i += 1) {
      const heat = this.heat[i];
      const flare = this.spark[i] ? Math.max(0, Math.sin(t * 0.9 + this.phase[i] * 5) - 0.75) * 4 : 0;
      const glow = Math.max(heat, flare);
      if (glow < 0.3) {
        continue;
      }
      const x = ox + this.rx[i] * scale;
      const y = oy + this.ry[i] * scale;
      pen.fillStyle = `rgba(245, 248, 255, ${Math.min(1, 0.4 + glow * 0.6)})`;
      pen.beginPath();
      pen.arc(x, y, 0.7 + glow * 0.9, 0, Math.PI * 2);
      pen.fill();
    }

    for (const hub of this.hubs) {
      const [red, green, blue] = TINTS[this.regions[this.regionOf[hub]].spec.tint];
      const x = ox + this.rx[hub] * scale;
      const y = oy + this.ry[hub] * scale;
      const lift = this.heat[hub];
      const radius = 7 + lift * 6;
      const halo = pen.createRadialGradient(x, y, 0, x, y, radius);
      halo.addColorStop(0, `rgba(${red}, ${green}, ${blue}, ${0.22 + lift * 0.3})`);
      halo.addColorStop(1, "rgba(0, 0, 0, 0)");
      pen.fillStyle = halo;
      pen.fillRect(x - radius, y - radius, radius * 2, radius * 2);
      pen.fillStyle = `rgba(240, 244, 255, ${0.75 + lift * 0.25})`;
      pen.beginPath();
      pen.arc(x, y, 1.4 + lift * 0.6, 0, Math.PI * 2);
      pen.fill();
    }
  }

  private randomIn(accept: (spec: RegionSpec) => boolean): number {
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const i = Math.floor(Math.random() * this.count);
      if (accept(this.regions[this.regionOf[i]].spec)) {
        return i;
      }
    }
    return Math.floor(Math.random() * this.count);
  }
}

function pairHash(a: number, b: number): number {
  let h = Math.imul(a ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(b + 0x632be5ab, 0xc2b2ae35);
  h ^= h >>> 13;
  h = Math.imul(h, 0x27d4eb2d);
  h ^= h >>> 15;
  return (h >>> 0) / 4294967296;
}

function gaussian(): number {
  const u = Math.max(1e-6, Math.random());
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * Math.random());
}

function mulberry32(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let next = Math.imul(state ^ (state >>> 15), 1 | state);
    next ^= next + Math.imul(next ^ (next >>> 7), 61 | next);
    return ((next ^ (next >>> 14)) >>> 0) / 4294967296;
  };
}
