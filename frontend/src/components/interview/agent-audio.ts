export type PresenceMood = "listening" | "thinking" | "speaking" | "waiting";

export type PresenceField = {
  mood: PresenceMood;
  energy: number;
  drift: number;
  flow: number;
  breath: number;
  gather: number;
};

export function isAgentAudio(identity: string, kind: string): boolean {
  return kind === "audio" && identity !== "candidate" && identity !== "recruiter";
}

export function presenceMood(value: string | null | undefined): PresenceMood {
  if (value === "listening" || value === "thinking" || value === "speaking" || value === "waiting") {
    return value;
  }
  return "listening";
}

export function presenceCaption(mood: PresenceMood): string {
  if (mood === "thinking") {
    return "Thinking";
  }
  if (mood === "speaking") {
    return "Speaking";
  }
  if (mood === "waiting") {
    return "Waiting";
  }
  return "I'm listening";
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}

export function presenceField(
  mood: PresenceMood,
  level: number,
  reducedMotion: boolean,
  held: PresenceMood = mood,
): PresenceField {
  const amount = clamp01(level);
  const voice = held === "speaking" ? amount > 0.05 : amount > 0.12;
  const live: PresenceMood = mood === "speaking" || voice ? "speaking" : mood;
  if (reducedMotion) {
    const energy = live === "speaking" ? 0.5 : live === "thinking" ? 0.4 : live === "waiting" ? 0.16 : 0.3;
    return { mood: live, energy, drift: 0, flow: 0, breath: 0, gather: live === "thinking" ? 0.7 : 0.2 };
  }
  if (live === "speaking") {
    return {
      mood: "speaking",
      energy: 0.58 + amount * 0.42,
      drift: 0.28 + amount * 0.45,
      flow: 0.72 + amount * 0.28,
      breath: 0.35 + amount * 0.4,
      gather: 0.15,
    };
  }
  if (live === "thinking") {
    return { mood: "thinking", energy: 0.66, drift: 0.2, flow: -0.35, breath: 0.22, gather: 0.9 };
  }
  if (live === "waiting") {
    return { mood: "waiting", energy: 0.2, drift: 0.07, flow: -0.15, breath: 0.1, gather: 0.1 };
  }
  return { mood: "listening", energy: 0.4, drift: 0.14, flow: -0.78, breath: 0.18, gather: 0.25 };
}

export function blendField(current: PresenceField, target: PresenceField, rate: number): PresenceField {
  const step = clamp01(rate);
  const mix = (from: number, to: number) => from + (to - from) * step;
  return {
    mood: target.mood,
    energy: mix(current.energy, target.energy),
    drift: mix(current.drift, target.drift),
    flow: mix(current.flow, target.flow),
    breath: mix(current.breath, target.breath),
    gather: mix(current.gather, target.gather),
  };
}
