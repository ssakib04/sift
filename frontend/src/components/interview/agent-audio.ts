export const INTERVIEWER_AVATAR_URL = "/avatars/interviewer.glb?v=brunette";
export const VISEME_MODEL_URL = "/sdk/viseme-model.bin";

export type AvatarPresentation = "scene" | "portrait";
export type PlaybackOwner = "element" | "avatar";

export type AgentPresence = "Listening" | "Thinking" | "Speaking";

export function agentPresence(state: string | null | undefined): AgentPresence {
  if (state === "speaking") {
    return "Speaking";
  }
  if (state === "thinking") {
    return "Thinking";
  }
  return "Listening";
}

export function isAgentAudio(identity: string, kind: string): boolean {
  return kind === "audio" && identity !== "candidate" && identity !== "recruiter";
}

export function avatarPresentation(input: {
  webgl: boolean;
  reducedMotion: boolean;
  modelAvailable: boolean;
  failed: boolean;
}): AvatarPresentation {
  if (!input.webgl || input.reducedMotion || !input.modelAvailable || input.failed) {
    return "portrait";
  }
  return "scene";
}

export function shouldHandAudioToAvatar(input: {
  presentation: AvatarPresentation;
  sceneReady: boolean;
  hasAgentAudio: boolean;
}): boolean {
  return input.presentation === "scene" && input.sceneReady && input.hasAgentAudio;
}

export function elementMuted(owner: PlaybackOwner): boolean {
  return owner === "avatar";
}

export function releaseAvatar(engine: { detachStream(): void; dispose(): void } | null): PlaybackOwner {
  if (engine) {
    engine.detachStream();
    engine.dispose();
  }
  return "element";
}
