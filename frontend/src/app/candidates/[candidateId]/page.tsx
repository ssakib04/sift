"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { CandidateReport, REPORTS, reportKey, type ReportKey } from "@/components/candidate-reports";
import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import {
  ApiError,
  CandidateRecord,
  ClaimVerification,
  InterviewAnalysis,
  InterviewQuality,
  InterviewScore,
  MasterAssessment,
  OpenedInterview,
  RecruiterQuiz,
  ReportRetry,
  TranscriptTurn,
  apiRequest,
  downloadAssessmentReport,
  rememberInterview,
} from "@/lib/api";

function CandidateProfilePage() {
  const params = useParams<{ candidateId: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const requested = reportKey(search.get("report"));
  const selected: ReportKey = requested || "assessment";
  const [candidate, setCandidate] = useState<CandidateRecord | null>(null);
  const [quiz, setQuiz] = useState<RecruiterQuiz | null>(null);
  const [assessment, setAssessment] = useState<MasterAssessment | null>(null);
  const [claims, setClaims] = useState<ClaimVerification | null>(null);
  const [score, setScore] = useState<InterviewScore | null>(null);
  const [quality, setQuality] = useState<InterviewQuality | null>(null);
  const [analysis, setAnalysis] = useState<InterviewAnalysis | null>(null);
  const [analysisStatus, setAnalysisStatus] = useState<"ready" | "pending" | "failed" | "missing">("missing");
  const [analysisNote, setAnalysisNote] = useState("");
  const [turns, setTurns] = useState<TranscriptTurn[]>([]);
  const [message, setMessage] = useState("");
  const [joining, setJoining] = useState(false);

  useEffect(() => {
    apiRequest<CandidateRecord>(`/api/v1/candidates/${params.candidateId}`)
      .then(setCandidate)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Could not open this candidate.");
      });
    apiRequest<RecruiterQuiz>(`/api/v1/candidates/${params.candidateId}/quiz`)
      .then(setQuiz)
      .catch(() => setQuiz(null));
    apiRequest<ClaimVerification>(`/api/v1/candidates/${params.candidateId}/claim-verification`)
      .then(setClaims)
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.code === "CLAIM_CHECK_NOT_FOUND" || error.code === "CANDIDATE_NOT_FOUND")) {
          setClaims(null);
          return;
        }
        setMessage(error instanceof Error ? error.message : "Could not load the CV follow-up prompts.");
      });
    apiRequest<MasterAssessment>(`/api/v1/candidates/${params.candidateId}/assessment`)
      .then((row) => {
        setAssessment(row);
        if (row.run_state === "running") {
          return;
        }
        if (row.run_state === "failed" && row.run_message) {
          setMessage(row.run_message);
        }
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "ASSESSMENT_NOT_FOUND") {
          setAssessment(null);
          return;
        }
        if (error instanceof ApiError && error.code === "ASSESSMENT_PENDING") {
          setAssessment(null);
          return;
        }
        if (error instanceof ApiError && error.code === "ASSESSMENT_FAILED") {
          setAssessment(null);
          setMessage(error.message);
          return;
        }
        if (error instanceof ApiError && error.code === "CANDIDATE_NOT_FOUND") {
          return;
        }
        setMessage(error instanceof Error ? error.message : "Could not load the master assessment.");
      });
    apiRequest<InterviewScore>(`/api/v1/candidates/${params.candidateId}/interview-score`)
      .then(setScore)
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.code === "INTERVIEW_SCORE_NOT_FOUND" || error.code === "INTERVIEW_NOT_ENDED" || error.code === "CANDIDATE_NOT_FOUND")) {
          setScore(null);
          return;
        }
        setMessage(error instanceof Error ? error.message : "Could not load the interview score.");
      });
    apiRequest<InterviewQuality>(`/api/v1/candidates/${params.candidateId}/interview-quality`)
      .then(setQuality)
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.code === "INTERVIEW_QUALITY_NOT_FOUND" || error.code === "INTERVIEW_NOT_ENDED" || error.code === "CANDIDATE_NOT_FOUND")) {
          setQuality(null);
          return;
        }
        setMessage(error instanceof Error ? error.message : "Could not load the interview quality review.");
      });
    apiRequest<InterviewAnalysis>(`/api/v1/candidates/${params.candidateId}/interview-analysis`)
      .then((row) => {
        setAnalysis(row);
        setAnalysisStatus("ready");
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "ANALYSIS_PENDING") {
          setAnalysis(null);
          setAnalysisStatus("pending");
          return;
        }
        if (error instanceof ApiError && error.code === "ANALYSIS_FAILED") {
          setAnalysis(null);
          setAnalysisStatus("failed");
          setAnalysisNote(error.message);
          return;
        }
        if (error instanceof ApiError && (error.code === "ANALYSIS_NOT_FOUND" || error.code === "CANDIDATE_NOT_FOUND")) {
          setAnalysis(null);
          setAnalysisStatus("missing");
          return;
        }
        setMessage(error instanceof Error ? error.message : "Could not load the question and answer analysis.");
      });
    apiRequest<TranscriptTurn[]>(`/api/v1/candidates/${params.candidateId}/transcript`)
      .then(setTurns)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "CANDIDATE_NOT_FOUND") {
          setTurns([]);
          return;
        }
        setMessage(error instanceof Error ? error.message : "Could not load the interview transcript.");
      });
  }, [params.candidateId]);

  useEffect(() => {
    if (analysisStatus !== "pending") {
      return;
    }
    let stopped = false;
    const timer = window.setInterval(() => {
      void apiRequest<InterviewAnalysis>(`/api/v1/candidates/${params.candidateId}/interview-analysis`)
        .then((row) => {
          if (stopped) {
            return;
          }
          setAnalysis(row);
          setAnalysisStatus("ready");
          setAnalysisNote("");
        })
        .catch((error: unknown) => {
          if (stopped || (error instanceof ApiError && error.code === "ANALYSIS_PENDING")) {
            return;
          }
          if (error instanceof ApiError && error.code === "ANALYSIS_FAILED") {
            setAnalysisStatus("failed");
            setAnalysisNote(error.message);
          }
        });
    }, 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [analysisStatus, params.candidateId]);

  function openReport(key: string) {
    router.replace(`/candidates/${params.candidateId}?report=${key}`);
  }

  async function retryReports() {
    setMessage("");
    try {
      await apiRequest<ReportRetry>(`/api/v1/candidates/${params.candidateId}/reports/retry`, { method: "POST" });
      const next = await apiRequest<CandidateRecord>(`/api/v1/candidates/${params.candidateId}`);
      setCandidate(next);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The reports could not be written again.");
    }
  }

  useEffect(() => {
    const progress = candidate?.report_progress;
    if (!progress || !Object.values(progress).includes("pending")) {
      return;
    }
    let stop = false;
    async function refresh() {
      const [next, scored, reviewed, written, checked, assessed] = await Promise.allSettled([
        apiRequest<CandidateRecord>(`/api/v1/candidates/${params.candidateId}`),
        apiRequest<InterviewScore>(`/api/v1/candidates/${params.candidateId}/interview-score`),
        apiRequest<InterviewQuality>(`/api/v1/candidates/${params.candidateId}/interview-quality`),
        apiRequest<InterviewAnalysis>(`/api/v1/candidates/${params.candidateId}/interview-analysis`),
        apiRequest<ClaimVerification>(`/api/v1/candidates/${params.candidateId}/claim-verification`),
        apiRequest<MasterAssessment>(`/api/v1/candidates/${params.candidateId}/assessment`),
      ]);
      if (stop) {
        return;
      }
      if (next.status === "fulfilled") {
        setCandidate(next.value);
      }
      if (scored.status === "fulfilled") {
        setScore(scored.value);
      }
      if (reviewed.status === "fulfilled") {
        setQuality(reviewed.value);
      }
      if (written.status === "fulfilled") {
        setAnalysis(written.value);
        setAnalysisStatus("ready");
      }
      if (checked.status === "fulfilled") {
        setClaims(checked.value);
      }
      if (assessed.status === "fulfilled" && assessed.value.run_state !== "running") {
        setAssessment(assessed.value);
      }
    }
    const timer = window.setInterval(() => {
      void refresh();
    }, 3000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [candidate?.report_progress, params.candidateId]);

  async function joinInterview() {
    if (!candidate) {
      return;
    }
    setJoining(true);
    try {
      const opened = await apiRequest<OpenedInterview>("/api/v1/interview-sessions/recruiter", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_id: candidate.id }),
      });
      rememberInterview(opened.session_id, opened.token, opened.role);
      router.push(`/interview/${opened.session_id}`);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The interview could not be opened.");
      setJoining(false);
    }
  }

  const progress = candidate?.report_progress || {};
  const reportSteps = ["qa", "claims", "score", "quality", "assessment"];
  const writing = reportSteps.some((step) => progress[step] === "pending");
  const finishedSteps = reportSteps.filter((step) => progress[step] && progress[step] !== "pending").length;

  function sectionNote(key: ReportKey): string {
    const state = progress[key];
    if (state === "pending") {
      return "Writing…";
    }
    if (state === "failed") {
      return "Could not finish";
    }
    if (key === "score" && score) {
      return score.overall_score.toFixed(1);
    }
    if (key === "quality" && quality) {
      return quality.overall_score.toFixed(1);
    }
    if (key === "quiz" && quiz?.status === "submitted" && quiz.score !== null) {
      return `${quiz.score} / 100`;
    }
    if (key === "checklist") {
      return candidate?.evaluations.length ? `${candidate.evaluations.length} checks` : "No CV score";
    }
    if (key === "assessment" && assessment?.overall_score != null) {
      return assessment.overall_score.toFixed(1);
    }
    if (key === "qa" && analysis) {
      return "Ready";
    }
    if (key === "claims" && claims) {
      return "Ready";
    }
    if (key === "transcript") {
      return turns.length ? `${turns.length} lines` : "Empty";
    }
    if (state === "ready") {
      return "Ready";
    }
    if (candidate?.interview_status === "ended") {
      return "—";
    }
    return "After the interview";
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl space-y-8">
        <Link href="/candidates" className="text-base text-ivory/70 hover:text-ivory">
          All candidates
        </Link>
        {message ? <p className="text-base text-mist">{message}</p> : null}
        {candidate ? (
          <article id="person" className="space-y-8">
            <header className="space-y-4">
              <PageHeader eyebrow={candidate.rank ? `Rank ${candidate.rank}` : "Unranked"} title={candidate.full_name || "Unnamed"} />
              <p className="text-lg text-ivory">{candidate.job_title || "Role not set"}</p>
              <p className="text-base text-ivory/75">{candidate.email}</p>
              {candidate.interview_status === "ended" ? (
                <p className="text-base text-ivory">Interview done{candidate.scheduled_label ? ` · ${candidate.scheduled_label}` : ""}</p>
              ) : candidate.invited ? (
                <div className="space-y-3">
                  {candidate.scheduled_label ? <p className="text-base text-ivory">Interview scheduled for {candidate.scheduled_label}.</p> : null}
                  <button type="button" onClick={() => void joinInterview()} disabled={joining} className={buttonClass()}>
                    Open interview
                  </button>
                </div>
              ) : null}
            </header>
            <Panel>
              <div className="grid gap-6 p-6 sm:grid-cols-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-mist">CV</p>
                  <p className="mt-2 font-display text-4xl text-ivory">{candidate.aggregate_score !== null ? candidate.aggregate_score.toFixed(2) : "—"}</p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-mist">Interview</p>
                  <p className="mt-2 font-display text-4xl text-ivory">{score ? score.overall_score.toFixed(1) : progress.score === "pending" ? "…" : "—"}</p>
                </div>
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-mist">Quiz</p>
                  <p className="mt-2 font-display text-4xl text-ivory">{quiz?.status === "submitted" && quiz.score !== null ? quiz.score : "—"}</p>
                </div>
              </div>
            </Panel>
            {writing ? (
              <div className="space-y-3">
                <p className="text-base text-ivory">Writing the report</p>
                <div className="h-1.5 overflow-hidden rounded-full bg-ivory/10">
                  <div className="h-full bg-action" style={{ width: `${(finishedSteps / reportSteps.length) * 100}%` }} />
                </div>
              </div>
            ) : null}
            <div className="grid items-start gap-8 lg:grid-cols-[16rem_minmax(0,1fr)]">
              <nav className="space-y-1">
                {REPORTS.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => openReport(item.key)}
                    className={`flex w-full items-baseline justify-between gap-3 rounded-control px-3 py-2.5 text-left ${selected === item.key ? "bg-ivory/10 text-ivory" : "text-ivory/75 hover:text-ivory"}`}
                  >
                    <span className="text-base">{item.label}</span>
                    <span className="shrink-0 text-sm text-mist">{sectionNote(item.key)}</span>
                  </button>
                ))}
              </nav>
              <Panel>
                <div className="p-6 sm:p-8">
                  <CandidateReport
                    selected={selected}
                    progress={progress}
                    onRetry={() => void retryReports()}
                    score={score}
                    quality={quality}
                    analysis={analysis}
                    analysisStatus={analysisStatus}
                    analysisNote={analysisNote}
                    claims={claims}
                    assessment={assessment}
                    onDownloadAssessment={() =>
                      void downloadAssessmentReport(candidate.id).catch((error: unknown) => {
                        setMessage(error instanceof Error ? error.message : "The report could not be downloaded.");
                      })
                    }
                    quiz={quiz}
                    evaluations={candidate.evaluations}
                    ended={candidate.interview_status === "ended"}
                    turns={turns}
                    candidateName={candidate.full_name || ""}
                  />
                </div>
              </Panel>
            </div>
          </article>
        ) : null}
      </div>
    </AppShell>
  );
}

export default function Page() {
  return (
    <Suspense
      fallback={
        <AppShell>
          <p className="text-sm text-mist">Opening candidate…</p>
        </AppShell>
      }
    >
      <CandidateProfilePage />
    </Suspense>
  );
}
