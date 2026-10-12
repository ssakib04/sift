"use client";

import { ConnectionState, Room, RoomEvent, Track } from "livekit-client";
import { useEffect, useRef, useState } from "react";

import { ChunkBuffer } from "@/components/interview/audio-buffer";
import { websocketBase } from "@/lib/api";

type VideoRoomProps = {
  sessionId: string;
  token: string;
  role: "candidate" | "recruiter";
  livekitUrl: string;
  livekitToken: string;
  record: boolean;
  onConnection: (state: string) => void;
};

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
  const recordRef = useRef(record);
  const [muted, setMuted] = useState(false);
  const [cameraOff, setCameraOff] = useState(false);
  const [status, setStatus] = useState("Connecting");
  const [attempt, setAttempt] = useState(0);
  const streamRef = useRef<MediaStream | null>(null);

  recordRef.current = record;

  useEffect(() => {
    let cancelled = false;
    let audio: WebSocket | null = null;
    let recorder: MediaRecorder | null = null;
    let context: AudioContext | null = null;
    let room: Room | null = null;
    const buffer = new ChunkBuffer();
    const startedAt = performance.now();
    let lastMark = 0;

    function report(next: string) {
      if (!cancelled) {
        setStatus(next);
        onConnection(next);
      }
    }

    function paintRemote(current: Room) {
      const media = new MediaStream();
      current.remoteParticipants.forEach((participant) => {
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
      if (current.remoteParticipants.size === 0) {
        return "Waiting for the other person";
      }
      return "Connected";
    }

    async function flushAudio() {
      if (!audio || audio.readyState !== WebSocket.OPEN) {
        return;
      }
      let chunk = buffer.shift();
      while (chunk) {
        if (!recordRef.current) {
          chunk = buffer.shift();
          continue;
        }
        try {
          audio.send(
            JSON.stringify({
              type: "chunk",
              speaker: chunk.speaker,
              start_time: chunk.startTime,
              end_time: chunk.endTime,
            }),
          );
          audio.send(chunk.data);
          await buffer.remove(chunk.id);
        } catch {
          buffer.unshift(chunk);
          return;
        }
        chunk = buffer.shift();
      }
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
        context = new AudioContext();
        void context.resume();
        const source = context.createMediaStreamSource(stream);
        const splitter = context.createChannelSplitter(2);
        const merger = context.createChannelMerger(1);
        const destination = context.createMediaStreamDestination();
        source.connect(splitter);
        splitter.connect(merger, 0, 0);
        merger.connect(destination);
        const mimeType = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : undefined;
        recorder = new MediaRecorder(destination.stream, mimeType ? { mimeType } : undefined);
        recorder.ondataavailable = (event) => {
          if (!event.data.size || !recordRef.current) {
            return;
          }
          const now = (performance.now() - startedAt) / 1000;
          const startTime = lastMark;
          lastMark = now;
          void event.data.arrayBuffer().then(async (data) => {
            await buffer.add({ speaker: role, startTime, endTime: now, data });
            await flushAudio();
          });
        };
        recorder.start(5000);
      } catch {
        report("The camera or microphone could not be opened.");
        return;
      }

      try {
        const stream = streamRef.current;
        if (!stream) {
          return;
        }
        const connection = new Room({ adaptiveStream: true, dynacast: true });
        room = connection;
        connection.on(RoomEvent.ConnectionStateChanged, () => report(describe(connection)));
        connection.on(RoomEvent.ParticipantConnected, () => report(describe(connection)));
        connection.on(RoomEvent.ParticipantDisconnected, () => report(describe(connection)));
        connection.on(RoomEvent.TrackSubscribed, () => paintRemote(connection));
        connection.on(RoomEvent.TrackUnsubscribed, () => paintRemote(connection));
        await connection.connect(livekitUrl, livekitToken);
        for (const track of stream.getTracks()) {
          await connection.localParticipant.publishTrack(track, {
            source: track.kind === "video" ? Track.Source.Camera : Track.Source.Microphone,
            videoEncoding: track.kind === "video" ? { maxBitrate: 1_700_000, maxFramerate: 30 } : undefined,
          });
        }
        if (!cancelled) {
          paintRemote(connection);
          report(describe(connection));
        }
      } catch {
        report("The video service could not be reached.");
        return;
      }

      await buffer.open();

      function connectAudio() {
        const socket = new WebSocket(`${websocketBase()}/api/v1/interview-sessions/${sessionId}/audio`);
        audio = socket;
        socket.onopen = () => {
          socket.send(JSON.stringify({ type: "auth", token }));
          void flushAudio();
        };
        socket.onclose = () => {
          if (cancelled) {
            return;
          }
          window.setTimeout(() => {
            if (!cancelled) {
              connectAudio();
            }
          }, 2000);
        };
      }

      connectAudio();
    }

    void start();
    const flushTimer = window.setInterval(() => {
      void flushAudio();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(flushTimer);
      if (recorder && recorder.state !== "inactive") {
        recorder.stop();
      }
      void context?.close();
      audio?.close();
      void room?.disconnect();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, [attempt, livekitToken, livekitUrl, onConnection, role, sessionId, token]);

  function toggleMute() {
    const next = !muted;
    setMuted(next);
    streamRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = !next;
    });
  }

  function toggleCamera() {
    const next = !cameraOff;
    setCameraOff(next);
    streamRef.current?.getVideoTracks().forEach((track) => {
      track.enabled = !next;
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
