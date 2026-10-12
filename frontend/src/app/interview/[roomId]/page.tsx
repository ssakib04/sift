"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { InCallCopilot } from "@/components/interview/in-call-copilot";
import { LiveTranscript } from "@/components/interview/live-transcript";
import { VideoRoom } from "@/components/interview/video-room";
import {
  InterviewAnalysis,
  InterviewCopilot,
  InterviewDetail,
  TranscriptTurn,
  apiRequest,
  bearer,
  recallInterview,
} from "@/lib/api";

export default function InterviewPage() {
  const params = useParams<{ roomId: string }>();
  const roomId = params.roomId;
  const [token, setToken] = useState("");
  const [role, setRole] = useState<"candidate" | "recruiter" | "">("");
  const [detail, setDetail] = useState<InterviewDetail | null>(null);
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [copilot, setCopilot] = useState<InterviewCopilot | null>(null);
  const [analysis, setAnalysis] = useState<InterviewAnalysis | null>(null);
  const [message, setMessage] = useState("");
  const [connection, setConnection] = useState("");
  const [ending, setEnding] = useState(false);
  const [livekit, setLivekit] = useState<{ url: string; token: string } | null>(null);

  const onConnection = useCallback((state: string) => {
    setConnection(state);
  }, []);

  useEffect(() => {
    const stored = recallInterview(roomId);
    if (!stored) {
      setMessage("Open this interview from your invitation link on this device.");
      return;
    }
    setToken(stored.token);
    setRole(stored.role);
  }, [roomId]);

  useEffect(() => {
    if (!token) {
      return;
    }
    let stop = false;
    async function load() {
      try {
        const next = await apiRequest<InterviewDetail>(`/api/v1/interview-sessions/${roomId}`, {
          headers: bearer(token),
        });
        if (!stop) {
          setDetail(next);
          setLivekit((current) => current ?? { url: next.livekit_url, token: next.livekit_token });
          setMessage("");
        }
      } catch (error: unknown) {
        if (!stop) {
          setMessage(error instanceof Error ? error.message : "This interview link is not valid.");
        }
      }
    }
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 3000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [roomId, token]);

  useEffect(() => {
    if (role !== "recruiter" || !token) {
      return;
    }
    let stop = false;
    async function loadTranscript() {
      try {
        const next = await apiRequest<TranscriptTurn[]>(`/api/v1/interview-sessions/${roomId}/transcript`, {
          headers: bearer(token),
        });
        if (!stop) {
          setTurns(next);
        }
      } catch {
        return;
      }
    }
    void loadTranscript();
    const timer = window.setInterval(() => {
      void loadTranscript();
    }, 2000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [role, roomId, token]);

  useEffect(() => {
    if (role !== "recruiter" || !token) {
      return;
    }
    let stop = false;
    async function loadCopilot() {
      try {
        const next = await apiRequest<InterviewCopilot>(`/api/v1/interview-sessions/${roomId}/copilot`, {
          headers: bearer(token),
        });
        if (!stop) {
          setCopilot(next);
        }
      } catch {
        return;
      }
    }
    void loadCopilot();
    const timer = window.setInterval(() => {
      void loadCopilot();
    }, 5000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [role, roomId, token]);

  useEffect(() => {
    if (role !== "recruiter" || !token || detail?.status !== "ended") {
      return;
    }
    let stop = false;
    async function loadAnalysis() {
      try {
        const next = await apiRequest<InterviewAnalysis>(`/api/v1/interview-sessions/${roomId}/analysis`, {
          headers: bearer(token),
        });
        if (!stop) {
          setAnalysis(next);
        }
      } catch {
        return;
      }
    }
    void loadAnalysis();
    const timer = window.setInterval(() => {
      void loadAnalysis();
    }, 3000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [detail?.status, role, roomId, token]);

  async function endCall() {
    setEnding(true);
    try {
      await apiRequest<InterviewDetail>(`/api/v1/interview-sessions/${roomId}/end`, {
        method: "POST",
        headers: bearer(token),
      });
      const next = await apiRequest<InterviewDetail>(`/api/v1/interview-sessions/${roomId}`, {
        headers: bearer(token),
      });
      setDetail(next);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The interview could not be ended.");
    } finally {
      setEnding(false);
    }
  }

  const ended = detail?.status === "ended";

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-5xl space-y-8">
        {role === "recruiter" ? (
          <Link href="/candidates" className="text-sm text-slate-400 hover:text-white">
            All candidates
          </Link>
        ) : null}
        <header className="space-y-2">
          <p className="text-sm uppercase tracking-[0.2em] text-slate-400">{detail?.company_name || "Sift"}</p>
          <h1 className="text-3xl font-semibold">{detail?.job_title || "Interview"}</h1>
          <p className="text-sm text-slate-400">{connection || detail?.status || "Opening the room"}</p>
        </header>
        {message ? <p className="text-sm text-slate-300">{message}</p> : null}
        {ended && role === "candidate" ? <p className="text-slate-200">This interview has ended.</p> : null}
        {detail && livekit && token && role && !ended ? (
          <VideoRoom
            sessionId={roomId}
            token={token}
            role={role}
            livekitUrl={livekit.url}
            livekitToken={livekit.token}
            record={detail.status === "started"}
            onConnection={onConnection}
          />
        ) : null}
        {detail && token && role && !ended ? (
          <button
            type="button"
            onClick={() => void endCall()}
            disabled={ending}
            className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-60"
          >
            End interview
          </button>
        ) : null}
        {role === "recruiter" ? (
          <div className="grid gap-6 lg:grid-cols-2">
            <LiveTranscript turns={turns} />
            <InCallCopilot copilot={copilot} />
          </div>
        ) : null}
        {role === "recruiter" && analysis ? (
          <section className="space-y-3">
            <h2 className="text-lg font-medium">Interview analysis</h2>
            <p className="text-sm text-slate-300">{analysis.summary}</p>
            <ul className="grid gap-2 text-sm sm:grid-cols-2">
              <li className="rounded-xl border border-slate-800 px-4 py-3">Relevance {analysis.relevance.toFixed(1)}</li>
              <li className="rounded-xl border border-slate-800 px-4 py-3">
                Technical accuracy {analysis.technical_accuracy.toFixed(1)}
              </li>
              <li className="rounded-xl border border-slate-800 px-4 py-3">Completeness {analysis.completeness.toFixed(1)}</li>
              <li className="rounded-xl border border-slate-800 px-4 py-3">Articulation {analysis.articulation.toFixed(1)}</li>
            </ul>
            {analysis.gaps.length > 0 ? (
              <ul className="list-disc pl-5 text-sm text-slate-200">
                {analysis.gaps.map((gap) => (
                  <li key={gap}>{gap}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}
      </div>
    </main>
  );
}
