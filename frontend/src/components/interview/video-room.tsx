"use client";

import { ConnectionState, Room, RoomEvent, Track } from "livekit-client";
import { PointerEvent as ReactPointerEvent, ReactNode, useEffect, useRef, useState } from "react";

type VideoRoomProps = {
  sessionId: string;
  token: string;
  role: "candidate" | "recruiter";
  livekitUrl: string;
  livekitToken: string;
  record: boolean;
  onConnection: (state: string) => void;
  onHangup: () => void;
  onQuiz?: () => void;
};

function isPerson(identity: string): boolean {
  return identity === "recruiter" || identity === "candidate";
}

function IconButton({
  label,
  danger = false,
  pressed = false,
  onClick,
  children,
}: {
  label: string;
  danger?: boolean;
  pressed?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={pressed}
      title={label}
      onClick={onClick}
      className={`grid h-12 w-12 place-items-center rounded-full text-ivory shadow-lift ${
        danger ? "bg-crimson hover:brightness-110" : pressed ? "bg-ivory text-night" : "bg-night/80 hover:bg-night"
      }`}
    >
      {children}
    </button>
  );
}

export function VideoRoom({
  sessionId,
  token,
  role,
  livekitUrl,
  livekitToken,
  record,
  onConnection,
  onHangup,
  onQuiz,
}: VideoRoomProps) {
  const localRef = useRef<HTMLVideoElement>(null);
  const remoteRef = useRef<HTMLVideoElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const roomRef = useRef<Room | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const dragRef = useRef<{ x: number; y: number; right: number; bottom: number } | null>(null);
  const [muted, setMuted] = useState(false);
  const [cameraOff, setCameraOff] = useState(false);
  const [status, setStatus] = useState("Connecting");
  const [attempt, setAttempt] = useState(0);
  const [hasRemote, setHasRemote] = useState(false);
  const [selfPlace, setSelfPlace] = useState({ right: 16, bottom: 88 });
  void sessionId;
  void token;
  void record;

  useEffect(() => {
    let cancelled = false;
    let room: Room | null = null;

    function report(next: string) {
      if (!cancelled) {
        setStatus(next);
        onConnection(next);
      }
    }

    function paintRemote(current: Room) {
      const media = new MediaStream();
      current.remoteParticipants.forEach((participant) => {
        if (!isPerson(participant.identity)) {
          return;
        }
        participant.trackPublications.forEach((publication) => {
          const track = publication.track?.mediaStreamTrack;
          if (track) {
            media.addTrack(track);
          }
        });
      });
      if (remoteRef.current) {
        remoteRef.current.srcObject = media.getTracks().length > 0 ? media : null;
      }
      if (!cancelled) {
        setHasRemote(media.getTracks().length > 0);
      }
    }

    function describe(current: Room): string {
      if (current.state === ConnectionState.Reconnecting) {
        return "Reconnecting";
      }
      if (current.state !== ConnectionState.Connected) {
        return "Connecting";
      }
      const people = [...current.remoteParticipants.values()].filter((participant) => isPerson(participant.identity));
      return people.length === 0 ? "Waiting for the other person" : "Connected";
    }

    async function start() {
      if (!window.isSecureContext) {
        report("The camera needs localhost or HTTPS on this device.");
        return;
      }
      if (!livekitUrl || !livekitToken) {
        report("The video service is not configured.");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        if (localRef.current) {
          localRef.current.srcObject = stream;
        }
        const connection = new Room({ adaptiveStream: true, dynacast: true });
        room = connection;
        roomRef.current = connection;
        connection.on(RoomEvent.ConnectionStateChanged, () => report(describe(connection)));
        connection.on(RoomEvent.ParticipantConnected, () => report(describe(connection)));
        connection.on(RoomEvent.ParticipantDisconnected, () => {
          paintRemote(connection);
          report(describe(connection));
        });
        connection.on(RoomEvent.TrackSubscribed, () => paintRemote(connection));
        connection.on(RoomEvent.TrackUnsubscribed, () => paintRemote(connection));
        connection.on(RoomEvent.TrackMuted, () => paintRemote(connection));
        connection.on(RoomEvent.TrackUnmuted, () => paintRemote(connection));
        try {
          await connection.connect(livekitUrl, livekitToken);
        } catch {
          stream.getTracks().forEach((mediaTrack) => mediaTrack.stop());
          report("The video service could not be reached.");
          return;
        }
        for (const mediaTrack of stream.getTracks()) {
          await connection.localParticipant.publishTrack(mediaTrack, {
            source: mediaTrack.kind === "video" ? Track.Source.Camera : Track.Source.Microphone,
          });
        }
        paintRemote(connection);
        report(describe(connection));
      } catch {
        report("The camera or microphone could not be opened.");
      }
    }

    void start();
    return () => {
      cancelled = true;
      roomRef.current = null;
      void room?.disconnect();
      streamRef.current?.getTracks().forEach((mediaTrack) => mediaTrack.stop());
      streamRef.current = null;
    };
  }, [attempt, livekitToken, livekitUrl, onConnection]);

  useEffect(() => {
    if (localRef.current && streamRef.current) {
      localRef.current.srcObject = streamRef.current;
    }
  }, [hasRemote]);

  async function setPublished(source: Track.Source, enabled: boolean) {
    const publication = roomRef.current?.localParticipant.getTrackPublication(source);
    if (!publication) {
      return;
    }
    if (enabled) {
      await publication.unmute();
    } else {
      await publication.mute();
    }
  }

  async function toggleMute() {
    const next = !muted;
    setMuted(next);
    streamRef.current?.getAudioTracks().forEach((mediaTrack) => {
      mediaTrack.enabled = !next;
    });
    try {
      await setPublished(Track.Source.Microphone, !next);
    } catch {
      return;
    }
  }

  async function toggleCamera() {
    const next = !cameraOff;
    setCameraOff(next);
    streamRef.current?.getVideoTracks().forEach((mediaTrack) => {
      mediaTrack.enabled = !next;
    });
    try {
      await setPublished(Track.Source.Camera, !next);
    } catch {
      return;
    }
  }

  function hangUp() {
    void roomRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((mediaTrack) => mediaTrack.stop());
    onHangup();
  }

  function beginDrag(event: ReactPointerEvent<HTMLDivElement>) {
    if (!hasRemote) {
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { x: event.clientX, y: event.clientY, right: selfPlace.right, bottom: selfPlace.bottom };
  }

  function moveDrag(event: ReactPointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    const stage = stageRef.current;
    if (!drag || !stage) {
      return;
    }
    const bounds = stage.getBoundingClientRect();
    const width = event.currentTarget.offsetWidth;
    const height = event.currentTarget.offsetHeight;
    const right = Math.min(Math.max(12, drag.right + (drag.x - event.clientX)), bounds.width - width - 12);
    const bottom = Math.min(Math.max(76, drag.bottom + (drag.y - event.clientY)), bounds.height - height - 12);
    setSelfPlace({ right, bottom });
  }

  function endDrag() {
    dragRef.current = null;
  }

  const blocked = status.startsWith("The camera") || status.startsWith("The video");
  const remoteLabel = role === "recruiter" ? "Candidate" : "Recruiter";

  return (
    <div ref={stageRef} className="relative h-full min-h-0 w-full overflow-hidden bg-night">
      <video
        ref={remoteRef}
        autoPlay
        playsInline
        className={`absolute inset-0 h-full w-full object-cover ${hasRemote ? "" : "hidden"}`}
      />
      <div
        className={
          hasRemote
            ? "absolute z-10 w-36 cursor-grab overflow-hidden rounded-card border border-ivory/20 shadow-lift active:cursor-grabbing sm:w-48"
            : "absolute inset-0"
        }
        style={hasRemote ? { right: selfPlace.right, bottom: selfPlace.bottom } : undefined}
        onPointerDown={hasRemote ? beginDrag : undefined}
        onPointerMove={hasRemote ? moveDrag : undefined}
        onPointerUp={hasRemote ? endDrag : undefined}
      >
        <video
          ref={localRef}
          autoPlay
          muted
          playsInline
          className={`w-full -scale-x-100 bg-night object-cover ${hasRemote ? "aspect-video" : "h-full"}`}
        />
        {hasRemote ? <p className="pointer-events-none absolute bottom-1 left-2 text-xs text-ivory">You</p> : null}
      </div>
      <p className="absolute left-4 top-4 rounded-full bg-night/70 px-3 py-1 text-xs text-ivory">
        {hasRemote ? remoteLabel : "You"} · {status}
      </p>
      {blocked ? (
        <button
          type="button"
          onClick={() => setAttempt((value) => value + 1)}
          className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ivory px-4 py-2 text-sm font-semibold text-night"
        >
          Open camera and microphone
        </button>
      ) : null}
      <div className="absolute inset-x-0 bottom-4 z-20 flex items-center justify-center gap-3">
        <IconButton label={muted ? "Unmute" : "Mute"} pressed={muted} onClick={() => void toggleMute()}>
          <MicIcon off={muted} />
        </IconButton>
        <IconButton label={cameraOff ? "Start camera" : "Stop camera"} pressed={cameraOff} onClick={() => void toggleCamera()}>
          <CameraIcon off={cameraOff} />
        </IconButton>
        {onQuiz ? (
          <IconButton label="Skill quiz" onClick={onQuiz}>
            <QuizIcon />
          </IconButton>
        ) : null}
        <IconButton label={role === "recruiter" ? "End interview" : "Leave"} danger onClick={hangUp}>
          <HangupIcon />
        </IconButton>
      </div>
    </div>
  );
}

function MicIcon({ off }: { off: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3Z" />
      <path d="M6 11a6 6 0 0 0 12 0M12 17v4" />
      {off ? <path d="M4 4l16 16" /> : null}
    </svg>
  );
}

function CameraIcon({ off }: { off: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M3 8a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8Z" />
      <path d="M15 10l6-3v10l-6-3" />
      {off ? <path d="M4 4l16 16" /> : null}
    </svg>
  );
}

function HangupIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M4 10c4-4 12-4 16 0l-2 3-3-1c-2 2-4 2-6 0l-3 1-2-3Z" />
    </svg>
  );
}

function QuizIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden>
      <path d="M6 4h12v16H6zM9 8h6M9 12h6M9 16h3" />
    </svg>
  );
}
