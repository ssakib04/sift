"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";

import { IdentityPanel } from "@/components/interview/identity-panel";
import { InCallCopilot } from "@/components/interview/in-call-copilot";
import { LiveTranscript } from "@/components/interview/live-transcript";
import { McqQuizModal } from "@/components/interview/mcq-quiz-modal";
import { VideoRoom } from "@/components/interview/video-room";
import { Atmosphere } from "@/components/ui/atmosphere";
import { Panel } from "@/components/ui/panel";
import {
  CopilotAnswer,
  IdentificationAck,
  InterviewAnalysis,
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
  const [closed, setClosed] = useState(false);
  const [endError, setEndError] = useState("");
  const [rail, setRail] = useState<"transcript" | "questions" | "identity">("transcript");
  const [quizOpen, setQuizOpen] = useState(false);
  const [identification, setIdentification] = useState<Identification | null>(null);
  const [faceConsent, setFaceConsent] = useState(false);
  const [allowingFace, setAllowingFace] = useState(false);
  const [faceDone, setFaceDone] = useState(false);
  const sendingFrame = useRef(false);
  const faceDoneRef = useRef(false);

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
    if (role !== "recruiter" || !token || closed || detail?.status === "ended") {
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
    if (role !== "recruiter" || !token || endError || !(closed || detail?.status === "ended") || analysis) {
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
  }, [analysis, closed, detail?.status, endError, role, roomId, token]);

  const sendFrame = useCallback(
    async (imageBase64: string) => {
      if (sendingFrame.current || faceDoneRef.current) {
        return;
      }
      sendingFrame.current = true;
      try {
        const ack = await apiRequest<IdentificationAck>(`/api/v1/interview-sessions/${roomId}/identification`, {
          method: "POST",
          headers: { ...bearer(token), "Content-Type": "application/json" },
          body: JSON.stringify({ image_base64: imageBase64 }),
        });
        if (ack.concluded) {
          faceDoneRef.current = true;
          setFaceDone(true);
        }
      } catch {
        return;
      } finally {
        sendingFrame.current = false;
      }
    },
    [roomId, token],
  );

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

  async function allowFaceCheck() {
    setAllowingFace(true);
    try {
      await apiRequest(`/api/v1/interview-sessions/${roomId}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...bearer(token) },
        body: JSON.stringify({ consent: true, biometric_consent: true }),
      });
      setDetail((current) => (current ? { ...current, biometric_consented_at: new Date().toISOString() } : current));
      setMessage("");
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "Face identification could not be enabled.");
    } finally {
      setAllowingFace(false);
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
    } catch (error: unknown) {
      const text = error instanceof Error ? error.message : "The interview could not be ended.";
      setClosed(false);
      setEndError(text);
      setMessage(text);
    } finally {
      setEnding(false);
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
    <div className="fixed inset-0 flex flex-col overflow-hidden text-ivory">
      <Atmosphere />
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
      {role === "candidate" && detail && !ended && !detail.biometric_consented_at ? (
        <div className="shrink-0 space-y-2 border-b border-ivory/10 px-4 py-3">
          <label className="flex items-start gap-3 text-sm text-mist">
            <input
              type="checkbox"
              checked={faceConsent}
              onChange={(event) => setFaceConsent(event.target.checked)}
              className="mt-1"
            />
            I agree to a face check. A frame from my camera is compared with the photo on my CV and with other stored
            candidate photos. The interviewer sees whether I match. If I do not agree, no identity is assumed.
          </label>
          <button
            type="button"
            disabled={!faceConsent || allowingFace}
            onClick={() => void allowFaceCheck()}
            className="text-sm text-ivory underline disabled:text-mist"
          >
            Allow face check
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
              captureFrames={role === "candidate" && Boolean(detail?.biometric_consented_at) && !faceDone}
              onFrame={sendFrame}
              onConnection={onConnection}
              onTranscript={role === "recruiter" ? hearTranscript : undefined}
              onHangup={hangUp}
              onQuiz={role === "candidate" ? () => setQuizOpen(true) : undefined}
            />
          ) : null}
          {ended && role === "recruiter" && !endError ? (
            <div className="h-full overflow-y-auto px-6 py-6">
              <AnalysisView analysis={analysis} failed={detail?.processing_status === "failed"} ending={ending} />
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
          <aside className="hidden w-[22rem] shrink-0 flex-col border-l border-ivory/10 bg-night/40 backdrop-blur-xl md:flex xl:w-[26rem]">
            <div className="flex shrink-0 border-b border-ivory/10">
              <button
                type="button"
                className={`flex-1 px-3 py-3 text-sm ${rail === "transcript" ? "text-ivory" : "text-mist"}`}
                onClick={() => setRail("transcript")}
              >
                Transcript
              </button>
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
              {rail === "transcript" ? (
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

function AnalysisView({
  analysis,
  failed,
  ending,
}: {
  analysis: InterviewAnalysis | null;
  failed: boolean;
  ending: boolean;
}) {
  if (!analysis) {
    return (
      <p className="text-sm text-mist">
        {failed ? "The analysis could not be prepared." : ending ? "Closing the call." : "Preparing the question and answer analysis."}
      </p>
    );
  }
  return (
    <div className="mx-auto max-w-3xl pb-10">
      <Panel wash>
        <div className="space-y-6 px-6 py-6">
      <h1 className="font-display text-3xl font-medium text-ivory">Interview analysis</h1>
      <p className="text-sm text-mist">{analysis.summary}</p>
      <ul className="grid gap-2 text-sm sm:grid-cols-2">
        <li><Panel><div className="px-4 py-3">Relevance {analysis.relevance.toFixed(1)}</div></Panel></li>
        <li><Panel><div className="px-4 py-3">Technical accuracy {analysis.technical_accuracy.toFixed(1)}</div></Panel></li>
        <li><Panel><div className="px-4 py-3">Completeness {analysis.completeness.toFixed(1)}</div></Panel></li>
        <li><Panel><div className="px-4 py-3">Articulation {analysis.articulation.toFixed(1)}</div></Panel></li>
      </ul>
      {analysis.gaps.length > 0 ? (
        <section className="space-y-1">
          <h2 className="text-sm font-medium text-ivory">Coverage gaps</h2>
          <ul className="list-disc pl-5 text-sm text-ivory">
            {analysis.gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {analysis.discrepancies.length > 0 ? (
        <section className="space-y-1">
          <h2 className="text-sm font-medium text-ivory">Discrepancies</h2>
          <ul className="list-disc pl-5 text-sm text-ivory">
            {analysis.discrepancies.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {analysis.pairs.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-ivory">Questions and answers</h2>
          <ul className="space-y-2">
            {analysis.pairs.map((pair) => (
              <li key={pair.pair_id}>
                <Panel>
                  <div className="space-y-1 px-4 py-3 text-sm">
                    <p className="font-medium text-ivory">
                      {pair.pair_id} · {pair.intent.replaceAll("_", " ")}
                    </p>
                    <p className="text-ivory">{pair.question}</p>
                    <p className="text-mist">{pair.answer || "No answer"}</p>
                    <p className="text-mist">{pair.citation}</p>
                    <p className="text-mist">
                      Relevance {pair.relevance.toFixed(1)} · Technical accuracy {pair.technical_accuracy.toFixed(1)} · Completeness {pair.completeness.toFixed(1)} · Articulation {pair.articulation.toFixed(1)}
                    </p>
                    {pair.query_ids.length > 0 ? <p className="text-mist">Checklist {pair.query_ids.join(", ")}</p> : null}
                  </div>
                </Panel>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {analysis.justifications.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-sm font-medium text-ivory">Evidence</h2>
          <ul className="space-y-2 text-sm">
            {analysis.justifications.map((item) => (
              <li key={`${item.citation}-${item.claim}`}>
                <p className="text-ivory">{item.claim}</p>
                <p className="text-mist">{item.citation}</p>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
        </div>
      </Panel>
    </div>
  );
}
