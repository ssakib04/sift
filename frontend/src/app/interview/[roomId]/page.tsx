"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { CvPacket } from "@/components/interview/cv-packet";
import { IdentityPanel, faceVerdict } from "@/components/interview/identity-panel";
import { InCallCopilot } from "@/components/interview/in-call-copilot";
import { LiveTranscript } from "@/components/interview/live-transcript";
import { McqQuizModal } from "@/components/interview/mcq-quiz-modal";
import { VideoRoom } from "@/components/interview/video-room";
import { Atmosphere, RoomSwitch } from "@/components/ui/atmosphere";
import { buttonClass } from "@/components/ui/button";
import {
  CopilotAnswer,
  Identification,
  InterviewCopilot,
  InterviewDetail,
  InterviewPacketView,
  TranscriptTurn,
  apiRequest,
  bearer,
  downloadInterviewPacket,
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
  const [rail, setRail] = useState<"transcript" | "questions" | "cv" | "identity">("transcript");
  const [packet, setPacket] = useState<InterviewPacketView | null>(null);
  const [downloading, setDownloading] = useState<"" | "html" | "pdf">("");
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
    async function loadPacket() {
      try {
        const next = await apiRequest<InterviewPacketView>(`/api/v1/interview-sessions/${roomId}/packet`, {
          headers: bearer(token),
        });
        if (!stop) {
          setPacket(next);
        }
      } catch {
        return;
      }
    }
    void loadPacket();
    const timer = window.setInterval(() => {
      void loadPacket();
    }, 5000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [closed, detail?.status, role, roomId, token]);

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
    const candidateId = detail?.candidate_id || "";
    setClosed(true);
    setEnding(true);
    setEndError("");
    try {
      await apiRequest<InterviewDetail>(`/api/v1/interview-sessions/${roomId}/end`, {
        method: "POST",
        headers: bearer(token),
      });
      setMessage("");
      if (candidateId) {
        router.replace(`/candidates/${candidateId}`);
        return;
      }
      const next = await apiRequest<InterviewDetail>(`/api/v1/interview-sessions/${roomId}`, {
        headers: bearer(token),
      });
      setDetail(next);
      if (next.candidate_id) {
        router.replace(`/candidates/${next.candidate_id}`);
        return;
      }
      setEnding(false);
    } catch (error: unknown) {
      const text = error instanceof Error ? error.message : "The interview could not be ended.";
      setClosed(false);
      setEndError(text);
      setMessage(text);
      setEnding(false);
    }
  }

  useEffect(() => {
    if (role !== "recruiter" || endError || ending) {
      return;
    }
    if (detail?.status === "ended" && detail.candidate_id) {
      router.replace(`/candidates/${detail.candidate_id}`);
    }
  }, [detail?.candidate_id, detail?.status, endError, ending, role, router]);

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

  async function downloadPacket(kind: "html" | "pdf") {
    if (!token || downloading) {
      return;
    }
    setDownloading(kind);
    try {
      await downloadInterviewPacket(roomId, token, kind);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Could not save the interview packet.");
    } finally {
      setDownloading("");
    }
  }

  function hangUp() {
    if (role === "recruiter") {
      void endCall();
      return;
    }
    setLeft(true);
  }

  return (
    <Atmosphere showSwitcher={false}>
    <div className="fixed inset-0 flex flex-col overflow-hidden text-ivory">
      <header className="relative z-30 flex h-14 shrink-0 items-center gap-4 border-b border-white/10 bg-[linear-gradient(180deg,rgb(48_24_32/0.55),rgb(18_10_14/0.28))] px-4 backdrop-blur-xl">
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
        <RoomSwitch />
        <p className="text-sm text-mist">{ended ? "Ended" : connection || "Opening"}</p>
      </header>
      {message ? <p className="relative shrink-0 px-4 py-2 text-sm text-mist">{message}</p> : null}
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
          {role === "recruiter" && identification?.required && !ended ? (
            <div className="pointer-events-none absolute right-3 top-3 z-40 w-72">
              <div className="pointer-events-auto space-y-2 rounded-card border border-white/15 bg-[linear-gradient(180deg,rgb(48_24_32/0.82),rgb(18_10_14/0.72))] p-3 shadow-lift backdrop-blur-xl">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-peach">
                  {faceVerdict(identification.status).title}
                </p>
                <p className="text-sm text-ivory">{identification.invited_name || "Candidate"}</p>
                <p className="text-sm text-mist">{identification.message || faceVerdict(identification.status).detail}</p>
                {identification.invited_similarity != null || identification.similarity != null ? (
                  <p className="text-sm text-ivory">
                    Likeness {Math.round((identification.invited_similarity ?? identification.similarity ?? 0) * 100)}%
                  </p>
                ) : null}
                {identification.can_join ? (
                  <p className="text-sm text-ivory">They can join.</p>
                ) : (
                  <button type="button" disabled={admitting} onClick={() => void admitCandidate()} className={buttonClass()}>
                    {admitting ? "Letting them in…" : "Let them in anyway"}
                  </button>
                )}
              </div>
            </div>
          ) : null}
          {ended && role === "recruiter" && !endError ? (
            <div className="grid h-full place-items-center px-6 text-center">
              <p className="text-ivory">{ending ? "Saving the interview." : "Opening this candidate."}</p>
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
          <aside className="hidden w-[22rem] shrink-0 flex-col border-l border-white/10 bg-[linear-gradient(180deg,rgb(48_24_32/0.5),rgb(18_10_14/0.38))] shadow-[inset_1px_0_0_rgb(255_220_214/0.2)] backdrop-blur-xl md:flex xl:w-[26rem]">
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
                className={`flex-1 px-2 py-3 text-sm ${rail === "cv" ? "text-ivory" : "text-mist"}`}
                onClick={() => setRail("cv")}
              >
                CV
              </button>
              <button
                type="button"
                className={`flex-1 px-2 py-3 text-sm ${rail === "identity" ? "text-ivory" : "text-mist"}`}
                onClick={() => setRail("identity")}
              >
                Identity
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {rail === "transcript" && detail?.conductor !== "agent" ? (
                <LiveTranscript turns={turns} candidateName={identification?.invited_name || ""} />
              ) : null}
              {rail === "identity" ? (
                <IdentityPanel
                  identification={identification}
                  admitting={admitting}
                  onAdmit={() => void admitCandidate()}
                />
              ) : null}
              {rail === "questions" ? (
                <InCallCopilot
                  copilot={copilot}
                  reply={copilotReply}
                  asking={asking}
                  onAsk={(question) => void askCopilot(question)}
                />
              ) : null}
              {rail === "cv" ? (
                <CvPacket packet={packet} downloading={downloading} onDownload={(kind) => void downloadPacket(kind)} />
              ) : null}
            </div>
          </aside>
        ) : null}
      </div>
      {quizOpen && role === "candidate" && token ? (
        <McqQuizModal sessionId={roomId} token={token} onClose={() => setQuizOpen(false)} />
      ) : null}
    </div>
    </Atmosphere>
  );
}
