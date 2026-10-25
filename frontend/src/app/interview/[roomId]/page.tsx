"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { IdentityPanel } from "@/components/interview/identity-panel";
import { InCallCopilot } from "@/components/interview/in-call-copilot";
import { LiveTranscript } from "@/components/interview/live-transcript";
import { McqQuizModal } from "@/components/interview/mcq-quiz-modal";
import { VideoRoom } from "@/components/interview/video-room";
import { buttonClass } from "@/components/ui/button";
import {
  CopilotAnswer,
  Identification,
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
  const router = useRouter();
  const roomId = params.roomId;
  const [token, setToken] = useState("");
  const [role, setRole] = useState<"candidate" | "recruiter" | "">("");
  const [detail, setDetail] = useState<InterviewDetail | null>(null);
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [copilot, setCopilot] = useState<InterviewCopilot | null>(null);
  const [copilotReply, setCopilotReply] = useState<CopilotAnswer | null>(null);
  const [asking, setAsking] = useState(false);
  const [message, setMessage] = useState("");
  const [connection, setConnection] = useState("");
  const [ending, setEnding] = useState(false);
  const [livekit, setLivekit] = useState<{ url: string; token: string } | null>(null);
  const [guestUrl, setGuestUrl] = useState("");
  const [copied, setCopied] = useState(false);
  const [left, setLeft] = useState(false);
  const [closed, setClosed] = useState(false);
  const [endError, setEndError] = useState("");
  const [rail, setRail] = useState<"transcript" | "questions" | "identity">("transcript");
  const [quizOpen, setQuizOpen] = useState(false);
  const [identification, setIdentification] = useState<Identification | null>(null);
  const [admitting, setAdmitting] = useState(false);

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
    if (role !== "recruiter" || !token || closed || detail?.status === "ended" || detail?.conductor === "agent") {
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
    }, 3000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [closed, detail?.conductor, detail?.status, role, roomId, token]);

  useEffect(() => {
    if (detail?.conductor === "agent") {
      setRail((current) => (current === "transcript" ? "questions" : current));
    }
  }, [detail?.conductor]);

  useEffect(() => {
    if (role !== "recruiter" || !token || closed || detail?.status === "ended") {
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
  }, [closed, detail?.status, role, roomId, token]);

  useEffect(() => {
    if (role !== "recruiter" || !token || closed || detail?.status === "ended" || identification?.concluded) {
      return;
    }
    let stop = false;
    async function loadIdentity() {
      try {
        const next = await apiRequest<Identification>(`/api/v1/interview-sessions/${roomId}/identification`, {
          headers: bearer(token),
        });
        if (!stop) {
          setIdentification(next);
        }
      } catch {
        return;
      }
    }
    void loadIdentity();
    const timer = window.setInterval(() => {
      void loadIdentity();
    }, 3000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [closed, detail?.status, identification?.concluded, role, roomId, token]);

  async function admitCandidate() {
    setAdmitting(true);
    try {
      const next = await apiRequest<Identification>(`/api/v1/interview-sessions/${roomId}/identification/admit`, {
        method: "POST",
        headers: bearer(token),
      });
      setIdentification(next);
      setMessage("");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The candidate could not be let in.");
    } finally {
      setAdmitting(false);
    }
  }

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
    setClosed(true);
    setEnding(true);
    setEndError("");
    let leaving = false;
    try {
      await apiRequest<InterviewDetail>(`/api/v1/interview-sessions/${roomId}/end`, {
        method: "POST",
        headers: bearer(token),
      });
      const next = await apiRequest<InterviewDetail>(`/api/v1/interview-sessions/${roomId}`, {
        headers: bearer(token),
      });
      setDetail(next);
      setMessage("");
      if (next.candidate_id) {
        leaving = true;
        router.push(`/candidates/${next.candidate_id}`);
      }
    } catch (error: unknown) {
      const text = error instanceof Error ? error.message : "The interview could not be ended.";
      setClosed(false);
      setEndError(text);
      setMessage(text);
    } finally {
      if (!leaving) {
        setEnding(false);
      }
    }
  }

  const ended = role === "recruiter" ? closed || detail?.status === "ended" : detail?.status === "ended";
  const inCall = Boolean(detail && livekit && token && role && !ended && !left);

  function hearTranscript(notice: { speaker: string; text: string; is_final?: boolean }) {
    setTurns((current) => {
      if (notice.is_final === false) {
        const live = {
          id: `live-${notice.speaker}`,
          speaker: notice.speaker,
          start_time: 0,
          end_time: 0,
          text: notice.text,
          confidence: 1,
          is_final: false,
        };
        const index = current.findIndex((item) => item.speaker === notice.speaker && item.is_final === false);
        if (index === -1) {
          return [...current, live];
        }
        const next = [...current];
        next[index] = { ...next[index], text: notice.text };
        return next;
      }
      const settled = current.filter((item) => !(item.speaker === notice.speaker && item.is_final === false));
      const previous = [...settled].reverse().find((item) => item.speaker === notice.speaker);
      if (previous?.text === notice.text) {
        return settled;
      }
      return [
        ...settled,
        {
          id: `said-${notice.speaker}-${settled.length}`,
          speaker: notice.speaker,
          start_time: 0,
          end_time: 0,
          text: notice.text,
          confidence: 1,
          is_final: true,
        },
      ];
    });
  }

  function hangUp() {
    if (role === "recruiter") {
      void endCall();
      return;
    }
    setLeft(true);
  }

  return (
    <div className="fixed inset-0 flex flex-col overflow-hidden bg-night text-ivory">
      <header className="relative flex h-12 shrink-0 items-center gap-4 border-b border-ivory/10 bg-night/35 px-4 backdrop-blur-md">
        {role === "recruiter" ? (
          <Link href="/candidates" className="text-sm text-mist hover:text-ivory">
            Candidates
          </Link>
        ) : (
          <span className="text-sm text-mist">{detail?.company_name || "Sift"}</span>
        )}
        <p className="min-w-0 flex-1 truncate text-sm text-ivory">{detail?.job_title || "Interview"}</p>
        {guestUrl && role === "recruiter" && !ended ? (
          <button
            type="button"
            className="text-sm text-mist hover:text-ivory"
            onClick={() => {
              void navigator.clipboard.writeText(guestUrl).then(
                () => setCopied(true),
                () => setCopied(false),
              );
            }}
          >
            {copied ? "Copied" : "Copy guest link"}
          </button>
        ) : null}
        <p className="text-sm text-mist">{ended ? "Ended" : connection || "Opening"}</p>
      </header>
      {message ? <p className="relative shrink-0 px-4 py-2 text-sm text-mist">{message}</p> : null}
      {role === "recruiter" && identification?.required && !identification.can_join ? (
        <div className="relative shrink-0 space-y-2 border-b border-ivory/10 px-4 py-3">
          <p className="text-sm text-ivory">{identification.message}</p>
          <button type="button" disabled={admitting} onClick={() => void admitCandidate()} className={buttonClass()}>
            Let them in
          </button>
        </div>
      ) : null}
      <div className="relative flex min-h-0 flex-1">
        <section className="relative min-w-0 flex-1">
          {inCall && livekit && role ? (
            <VideoRoom
              sessionId={roomId}
              token={token}
              role={role}
              livekitUrl={livekit.url}
              livekitToken={livekit.token}
              record={detail?.status === "started"}
              onConnection={onConnection}
              onTranscript={role === "recruiter" && detail?.conductor !== "agent" ? hearTranscript : undefined}
              onHangup={hangUp}
              onQuiz={role === "candidate" ? () => setQuizOpen(true) : undefined}
            />
          ) : null}
          {ended && role === "recruiter" && !endError ? (
            <div className="grid h-full place-items-center px-6 text-center">
              <div className="max-w-md space-y-3">
                <p className="text-ivory">{ending ? "Saving the interview." : "This interview has ended."}</p>
                <p className="text-sm text-mist">The reports are on this candidate's page.</p>
                {!ending && detail?.candidate_id ? (
                  <Link href={`/candidates/${detail.candidate_id}`} className="text-sm text-ivory underline">
                    Open reports
                  </Link>
                ) : null}
              </div>
            </div>
          ) : null}
          {left && !ended ? (
            <div className="grid h-full place-items-center px-6 text-center">
              <p className="text-ivory">You left the call. It stays open until the recruiter ends it.</p>
            </div>
          ) : null}
          {ended && role === "candidate" ? (
            <div className="grid h-full place-items-center px-6 text-center">
              <p className="text-ivory">This interview has ended.</p>
            </div>
          ) : null}
          {!token ? (
            <div className="grid h-full place-items-center px-6 text-center">
              <p className="text-mist">Open this interview from your invitation link on this device.</p>
            </div>
          ) : null}
        </section>
        {role === "recruiter" && !ended ? (
          <aside className="hidden w-[22rem] shrink-0 flex-col border-l border-white/10 bg-[linear-gradient(180deg,rgb(40_20_26/0.36),rgb(16_10_12/0.46))] backdrop-blur-xl md:flex xl:w-[26rem]">
            <div className="flex shrink-0 border-b border-ivory/10">
              {detail?.conductor === "agent" ? null : (
                <button
                  type="button"
                  className={`flex-1 px-3 py-3 text-sm ${rail === "transcript" ? "text-ivory" : "text-mist"}`}
                  onClick={() => setRail("transcript")}
                >
                  Transcript
                </button>
              )}
              <button
                type="button"
                className={`flex-1 px-3 py-3 text-sm ${rail === "questions" ? "text-ivory" : "text-mist"}`}
                onClick={() => setRail("questions")}
              >
                Questions
              </button>
              <button
                type="button"
                className={`flex-1 px-3 py-3 text-sm ${rail === "identity" ? "text-ivory" : "text-mist"}`}
                onClick={() => setRail("identity")}
              >
                Identity
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {rail === "transcript" && detail?.conductor !== "agent" ? (
                <LiveTranscript turns={turns} candidateName={identification?.invited_name || ""} />
              ) : null}
              {rail === "identity" ? <IdentityPanel identification={identification} /> : null}
              {rail === "questions" ? (
                <InCallCopilot
                  copilot={copilot}
                  reply={copilotReply}
                  asking={asking}
                  onAsk={(question) => void askCopilot(question)}
                />
              ) : null}
            </div>
          </aside>
        ) : null}
      </div>
      {quizOpen && role === "candidate" && token ? (
        <McqQuizModal sessionId={roomId} token={token} onClose={() => setQuizOpen(false)} />
      ) : null}
    </div>
  );
}
