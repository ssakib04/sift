"use client";

import { useEffect, useRef } from "react";

import { NeuralField } from "@/components/interview/neural-field";

type InterviewerAvatarProps = {
  voice: MediaStream | null;
  heard: MediaStream | null;
};

type Meter = { read(): number; close(): void };

export function InterviewerAvatar({ voice, heard }: InterviewerAvatarProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const voiceMeter = useRef<Meter | null>(null);
  const heardMeter = useRef<Meter | null>(null);
  const contextRef = useRef<AudioContext | null>(null);

  useEffect(() => {
    const context = new AudioContext();
    contextRef.current = context;
    const wake = () => void context.resume();
    wake();
    window.addEventListener("pointerdown", wake);
    return () => {
      window.removeEventListener("pointerdown", wake);
      contextRef.current = null;
      void context.close();
    };
  }, []);

  useEffect(() => {
    const context = contextRef.current;
    if (!context || !voice || voice.getAudioTracks().length === 0) {
      return;
    }
    const meter = speechMeter(context, voice);
    voiceMeter.current = meter;
    return () => {
      voiceMeter.current = null;
      meter.close();
    };
  }, [voice]);

  useEffect(() => {
    const context = contextRef.current;
    if (!context || !heard || heard.getAudioTracks().length === 0) {
      return;
    }
    const meter = speechMeter(context, heard);
    heardMeter.current = meter;
    return () => {
      heardMeter.current = null;
      meter.close();
    };
  }, [heard]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const pen = canvas?.getContext("2d");
    if (!canvas || !pen) {
      return;
    }
    const surface: HTMLCanvasElement = canvas;
    const paint: CanvasRenderingContext2D = pen;
    const field = new NeuralField();
    let frame = 0;
    let last = performance.now();

    function tick(now: number) {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const parent = surface.parentElement;
      const width = parent?.clientWidth ?? 960;
      const height = parent?.clientHeight ?? 540;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      if (surface.width !== Math.floor(width * ratio) || surface.height !== Math.floor(height * ratio)) {
        surface.width = Math.floor(width * ratio);
        surface.height = Math.floor(height * ratio);
      }
      paint.setTransform(ratio, 0, 0, ratio, 0, 0);
      field.step(dt, {
        voice: voiceMeter.current?.read() ?? 0,
        heard: heardMeter.current?.read() ?? 0,
      });
      field.draw(paint, width, height);
      frame = requestAnimationFrame(tick);
    }

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div className="absolute inset-0 bg-black" role="img" aria-label="AI interviewer">
      <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" />
    </div>
  );
}

function speechMeter(context: AudioContext, stream: MediaStream): Meter {
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  const silent = context.createGain();
  analyser.fftSize = 2048;
  analyser.smoothingTimeConstant = 0.35;
  silent.gain.value = 0;
  source.connect(analyser);
  analyser.connect(silent);
  silent.connect(context.destination);
  const bins = new Uint8Array(analyser.frequencyBinCount);
  const binHz = context.sampleRate / analyser.fftSize;
  const start = Math.max(0, Math.floor(250 / binHz));
  const end = Math.min(bins.length, Math.ceil(3400 / binHz));
  return {
    read() {
      analyser.getByteFrequencyData(bins);
      let sum = 0;
      for (let index = start; index < end; index += 1) {
        sum += bins[index];
      }
      const average = sum / Math.max(1, end - start) / 255;
      return Math.min(1, Math.max(0, (average - 0.035) / 0.16) ** 0.7);
    },
    close() {
      source.disconnect();
      analyser.disconnect();
      silent.disconnect();
    },
  };
}
