"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { InCallCopilot } from "@/components/interview/in-call-copilot";
import { LiveTranscript } from "@/components/interview/live-transcript";
import { VideoRoom } from "@/components/interview/video-room";
import { buttonClass } from "@/components/ui/button";
import { fieldClass } from "@/components/ui/field";
import { GuestFrame } from "@/components/ui/guest-frame";
import { Panel } from "@/components/ui/panel";
import { PageHeader } from "@/components/ui/page-header";
import {
  CopilotAnswer,
  InterviewAnalysis,
  InterviewCopilot,
  InterviewDetail,
  TranscriptTurn,
  apiRequest,
  bearer,
  recallInterview,
  recallPracticeLink,
} from "@/lib/api";

export default function InterviewPage() {
  const params = useParams<{ roomId: string }>();
  const roomId = params.roomId;
  const [token, setToken] = useState("");
  const [role, setRole] = useState<"candidate" | "recruiter" | "">("");
  const [detail, setDetail] = useState<InterviewDetail | null>(null);
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [copilot, setCopilot] = useState<InterviewCopilot | null>(null);
  const [copilotReply, setCopilotReply] = useState<CopilotAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [analysis, setAnalysis] = useState<InterviewAnalysis | null>(null);
  const [message, setMessage] = useState("");
  const [connection, setConnection] = useState("");
  const [ending, setEnding] = useState(false);
  const [livekit, setLivekit] = useState<{ url: string; token: string } | null>(null);
  const [guestUrl, setGuestUrl] = useState("");
  const [copied, setCopied] = useState(false);
  const [left, setLeft] = useState(false);

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
    setGuestUrl(recallPracticeLink(roomId));
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
    }, 1000);
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

  async function askCopilot(question: string) {
    setAsking(true);
    try {
      const next = await apiRequest<CopilotAnswer>(`/api/v1/interview-sessions/${roomId}/copilot`, {
        method: "POST",
        headers: { ...bearer(token), "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      setCopilotReply(next);
      setMessage("");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The copilot could not answer.");
    } finally {
      setAsking(false);
    }
  }

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
    <GuestFrame wide>
      <div className="space-y-8">
        {role === "recruiter" ? (
          <Link href="/candidates" className="text-sm text-mist hover:text-ivory">
            All candidates
          </Link>
        ) : null}
        <PageHeader
          eyebrow={detail?.company_name || "Sift"}
          title={detail?.job_title || "Interview"}
          lede={connection || detail?.status || "Opening the room"}
        />
        {message ? <p className="text-sm text-mist">{message}</p> : null}
        {role === "recruiter" && detail?.status === "invited" ? (
          <p className="text-sm text-mist">Waiting for the guest to open the link and agree. Speech is saved after they join.</p>
        ) : null}
        {role === "recruiter" && guestUrl ? (
          <Panel>
            <section className="flex flex-wrap items-center gap-3 p-5">
              <input readOnly value={guestUrl} aria-label="Guest link" className={`min-w-0 flex-1 ${fieldClass}`} />
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard.writeText(guestUrl).then(
                    () => setCopied(true),
                    () => setCopied(false),
                  );
                }}
                className={buttonClass("secondary")}
              >
                {copied ? "Copied" : "Copy guest link"}
              </button>
            </section>
          </Panel>
        ) : null}
        {ended && role === "candidate" ? <p className="text-ivory">This interview has ended.</p> : null}
        {detail && livekit && token && role && !ended && !left ? (
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
        {role === "recruiter" && detail && token && !ended ? (
          <button type="button" onClick={() => void endCall()} disabled={ending} className={buttonClass()}>
            End interview
          </button>
        ) : null}
        {role === "candidate" && !ended && !left ? (
          <button type="button" onClick={() => setLeft(true)} className={buttonClass("secondary")}>
            Leave
          </button>
        ) : null}
        {left && !ended ? <p className="text-sm text-mist">You left the call. It stays open until the recruiter ends it.</p> : null}
        {role === "recruiter" ? (
          <div className="grid gap-6 lg:grid-cols-2">
            <LiveTranscript turns={turns} />
            <InCallCopilot copilot={copilot} reply={copilotReply} asking={asking} onAsk={(question) => void askCopilot(question)} />
          </div>
        ) : null}
        {role === "recruiter" && analysis ? (
          <section className="space-y-3">
            <h2 className="font-display text-2xl font-medium text-ivory">Interview analysis</h2>
            <p className="text-sm text-mist">{analysis.summary}</p>
            <ul className="grid gap-2 text-sm sm:grid-cols-2">
              <li><Panel><div className="px-4 py-3">Relevance {analysis.relevance.toFixed(1)}</div></Panel></li>
              <li><Panel><div className="px-4 py-3">Technical accuracy {analysis.technical_accuracy.toFixed(1)}</div></Panel></li>
              <li><Panel><div className="px-4 py-3">Completeness {analysis.completeness.toFixed(1)}</div></Panel></li>
              <li><Panel><div className="px-4 py-3">Articulation {analysis.articulation.toFixed(1)}</div></Panel></li>
            </ul>
            {analysis.gaps.length > 0 ? (
              <ul className="list-disc pl-5 text-sm text-ivory">
                {analysis.gaps.map((gap) => (
                  <li key={gap}>{gap}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}
      </div>
    </GuestFrame>
  );
}
