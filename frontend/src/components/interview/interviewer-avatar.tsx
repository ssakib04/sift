"use client";

import { useEffect, useRef, useState } from "react";
import {
  avatarPresentation,
  INTERVIEWER_AVATAR_URL,
  type PlaybackOwner,
  releaseAvatar,
  shouldHandAudioToAvatar,
  VISEME_MODEL_URL,
} from "@/components/interview/agent-audio";
import { InterviewerPortrait } from "@/components/interview/interviewer-portrait";

type TalkingEngine = {
  ready: Promise<void>;
  attachStream: (stream: MediaStream) => Promise<void>;
  detachStream: () => void;
  dispose: () => void;
};

type InterviewerAvatarProps = {
  stream: MediaStream | null;
  mouth: number;
  onPlaybackOwner: (owner: PlaybackOwner) => void;
  onPortraitJaw: (needed: boolean) => void;
};

function webglSupported(): boolean {
  try {
    const canvas = document.createElement("canvas");
    const gl = canvas.getContext("webgl2") || canvas.getContext("webgl");
    if (!gl) {
      return false;
    }
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return true;
  } catch {
    return false;
  }
}

export function InterviewerAvatar({ stream, mouth, onPlaybackOwner, onPortraitJaw }: InterviewerAvatarProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<TalkingEngine | null>(null);
  const ownerRef = useRef(onPlaybackOwner);
  const jawRef = useRef(onPortraitJaw);
  ownerRef.current = onPlaybackOwner;
  jawRef.current = onPortraitJaw;
  const [presentation, setPresentation] = useState<"pending" | "scene" | "portrait">("pending");
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [audioAttempt, setAudioAttempt] = useState(0);
  const attachFailedRef = useRef(false);

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let cancelled = false;

    async function decide() {
      const webgl = webglSupported();
      let modelAvailable = false;
      if (webgl && !motion.matches) {
        try {
          const [avatarHead, visemeHead] = await Promise.all([
            fetch(INTERVIEWER_AVATAR_URL, { method: "HEAD" }),
            fetch(VISEME_MODEL_URL, { method: "HEAD" }),
          ]);
          const present = (response: Response) => response.ok || response.status === 405;
          modelAvailable = present(avatarHead) && present(visemeHead);
        } catch {
          modelAvailable = false;
        }
      }
      if (cancelled) {
        return;
      }
      const next = avatarPresentation({
        webgl,
        reducedMotion: motion.matches,
        modelAvailable,
        failed,
      });
      setPresentation(next);
    }

    void decide();
    const onMotion = () => {
      void decide();
    };
    motion.addEventListener("change", onMotion);
    return () => {
      cancelled = true;
      motion.removeEventListener("change", onMotion);
    };
  }, [failed]);

  useEffect(() => {
    jawRef.current(presentation === "portrait");
  }, [presentation]);

  useEffect(() => {
    if (presentation !== "scene") {
      setReady(false);
      return;
    }
    const container = containerRef.current;
    if (!container) {
      return;
    }
    let cancelled = false;

    void import("@interviewflowai/talking-avatar")
      .then(({ TalkingAvatar }) => {
        if (cancelled || !containerRef.current) {
          return;
        }
        const created = new TalkingAvatar({
          container: containerRef.current,
          avatarUrl: INTERVIEWER_AVATAR_URL,
          modelUrl: VISEME_MODEL_URL,
          streamDelayMs: 150,
        });
        if (cancelled) {
          ownerRef.current(releaseAvatar(created));
          return;
        }
        engineRef.current = created;
        created.ready
          .then(() => {
            if (!cancelled) {
              setReady(true);
            }
          })
          .catch(() => {
            if (!cancelled) {
              setFailed(true);
              setPresentation("portrait");
            }
          });
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true);
          setPresentation("portrait");
        }
      });

    return () => {
      cancelled = true;
      const current = engineRef.current;
      engineRef.current = null;
      ownerRef.current(releaseAvatar(current));
      setReady(false);
    };
  }, [presentation]);

  useEffect(() => {
    const retry = () => {
      if (attachFailedRef.current) {
        attachFailedRef.current = false;
        setAudioAttempt((attempt) => attempt + 1);
      }
    };
    window.addEventListener("pointerdown", retry);
    return () => window.removeEventListener("pointerdown", retry);
  }, []);

  useEffect(() => {
    const engine = engineRef.current;
    const handOff = shouldHandAudioToAvatar({
      presentation: presentation === "scene" ? "scene" : "portrait",
      sceneReady: ready,
      hasAgentAudio: Boolean(stream && stream.getAudioTracks().length > 0),
    });
    if (!engine || !handOff || !stream) {
      engine?.detachStream();
      ownerRef.current("element");
      return;
    }
    let cancelled = false;
    attachFailedRef.current = false;
    engine.attachStream(stream).then(
      () => {
        if (cancelled) {
          engine.detachStream();
          return;
        }
        ownerRef.current("avatar");
      },
      () => {
        if (cancelled) {
          return;
        }
        engine.detachStream();
        ownerRef.current("element");
        attachFailedRef.current = true;
      },
    );
    return () => {
      cancelled = true;
      engine.detachStream();
      ownerRef.current("element");
    };
  }, [audioAttempt, presentation, ready, stream]);

  if (presentation === "portrait") {
    return <InterviewerPortrait mouth={mouth} />;
  }

  return (
    <div className="absolute inset-0 bg-[#241010]" role="img" aria-label="Interviewer">
      <div ref={containerRef} className="absolute inset-0" />
      {presentation === "pending" || !ready ? (
        <p className="pointer-events-none absolute inset-x-0 bottom-24 text-center text-sm text-ivory/80" aria-live="polite">
          The interviewer is coming into view.
        </p>
      ) : null}
    </div>
  );
}
