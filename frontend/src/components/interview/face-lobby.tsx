"use client";

import { useEffect, useRef, useState } from "react";

export function FaceLobby({
  active,
  onFrame,
  onError,
}: {
  active: boolean;
  onFrame: (imageBase64: string) => void;
  onError?: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const onErrorRef = useRef(onError);
  const [error, setError] = useState("");
  onErrorRef.current = onError;

  useEffect(() => {
    if (!active) {
      return;
    }
    let stream: MediaStream | null = null;
    let stop = false;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "user" }, audio: false })
      .then((media) => {
        if (stop) {
          media.getTracks().forEach((track) => track.stop());
          return;
        }
        stream = media;
        if (videoRef.current) {
          videoRef.current.srcObject = media;
        }
      })
      .catch(() => {
        if (!stop) {
          setError("The camera could not be opened. A recruiter can still let you in.");
          onErrorRef.current?.();
        }
      });
    return () => {
      stop = true;
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [active]);

  useEffect(() => {
    if (!active) {
      return;
    }
    const send = onFrame;
    let stop = false;

    function grab() {
      const video = videoRef.current;
      if (stop || !video || video.videoWidth === 0) {
        return;
      }
      const scale = Math.min(1, 480 / video.videoWidth);
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      const context = canvas.getContext("2d");
      if (!context) {
        return;
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const payload = canvas.toDataURL("image/jpeg", 0.8).split(",")[1];
      if (payload) {
        send(payload);
      }
    }

    const first = window.setTimeout(grab, 800);
    const timer = window.setInterval(grab, 1000);
    return () => {
      stop = true;
      window.clearTimeout(first);
      window.clearInterval(timer);
    };
  }, [active, onFrame]);

  if (!active) {
    return null;
  }

  return (
    <div className="space-y-3">
      <video ref={videoRef} autoPlay playsInline muted className="aspect-video w-full rounded-control bg-black object-cover" />
      <p className="text-sm text-mist">{error || "Look at the camera. This takes a few seconds."}</p>
    </div>
  );
}
