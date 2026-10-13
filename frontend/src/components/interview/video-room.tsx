"use client";

import { ConnectionState, Room, RoomEvent, Track } from "livekit-client";
import { useEffect, useRef, useState } from "react";

type VideoRoomProps = {
  sessionId: string;
  token: string;
  role: "candidate" | "recruiter";
  livekitUrl: string;
  livekitToken: string;
  record: boolean;
  onConnection: (state: string) => void;
};

function isPerson(identity: string): boolean {
  return identity === "recruiter" || identity === "candidate";
}

export function VideoRoom({
  sessionId,
  token,
  role,
  livekitUrl,
  livekitToken,
  record,
  onConnection,
}: VideoRoomProps) {
  const localRef = useRef<HTMLVideoElement>(null);
  const remoteRef = useRef<HTMLVideoElement>(null);
  const [muted, setMuted] = useState(false);
  const [cameraOff, setCameraOff] = useState(false);
  const [status, setStatus] = useState("Connecting");
  const [attempt, setAttempt] = useState(0);
  const streamRef = useRef<MediaStream | null>(null);
  void sessionId;
  void token;
  void role;
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
        remoteRef.current.srcObject = media;
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
        connection.on(RoomEvent.ConnectionStateChanged, () => report(describe(connection)));
        connection.on(RoomEvent.ParticipantConnected, () => report(describe(connection)));
        connection.on(RoomEvent.ParticipantDisconnected, () => report(describe(connection)));
        connection.on(RoomEvent.TrackSubscribed, () => paintRemote(connection));
        connection.on(RoomEvent.TrackUnsubscribed, () => paintRemote(connection));
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
            videoEncoding: mediaTrack.kind === "video" ? { maxBitrate: 1_700_000, maxFramerate: 30 } : undefined,
          });
        }
        if (!cancelled) {
          paintRemote(connection);
          report(describe(connection));
        }
      } catch {
        report("The camera or microphone could not be opened.");
      }
    }

    void start();
    return () => {
      cancelled = true;
      void room?.disconnect();
      streamRef.current?.getTracks().forEach((mediaTrack) => mediaTrack.stop());
      streamRef.current = null;
    };
  }, [attempt, livekitToken, livekitUrl, onConnection]);

  function toggleMute() {
    const next = !muted;
    setMuted(next);
    streamRef.current?.getAudioTracks().forEach((mediaTrack) => {
      mediaTrack.enabled = !next;
    });
  }

  function toggleCamera() {
    const next = !cameraOff;
    setCameraOff(next);
    streamRef.current?.getVideoTracks().forEach((mediaTrack) => {
      mediaTrack.enabled = !next;
    });
  }

  return (
    <section className="space-y-4">
      <p className="text-sm text-slate-300">{status}</p>
      <div className="grid gap-4 md:grid-cols-2">
        <video ref={localRef} autoPlay muted playsInline className="aspect-video w-full rounded-xl bg-slate-900" />
        <video ref={remoteRef} autoPlay playsInline className="aspect-video w-full rounded-xl bg-slate-900" />
      </div>
      <div className="flex flex-wrap gap-3">
        {status.startsWith("The camera") || status.startsWith("The video") ? (
          <button
            type="button"
            onClick={() => setAttempt((value) => value + 1)}
            className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-950"
          >
            Open camera and microphone
          </button>
        ) : null}
        <button type="button" onClick={toggleMute} className="rounded-lg border border-slate-700 px-4 py-2 text-sm">
          {muted ? "Unmute" : "Mute"}
        </button>
        <button type="button" onClick={toggleCamera} className="rounded-lg border border-slate-700 px-4 py-2 text-sm">
          {cameraOff ? "Start camera" : "Stop camera"}
        </button>
      </div>
    </section>
  );
}
