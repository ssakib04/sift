"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { CandidateReport, REPORTS, reportKey } from "@/components/candidate-reports";
import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import {
  AnalysisRun,
  ApiError,
  AssessmentRun,
  CandidateRecord,
  ClaimVerification,
  InterviewAnalysis,
  InterviewQuality,
  InterviewScore,
  MasterAssessment,
  OpenedInterview,
  RecruiterQuiz,
  apiRequest,
  downloadAssessmentReport,
  rememberInterview,
} from "@/lib/api";

function CandidateProfilePage() {
  const params = useParams<{ candidateId: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const selected = reportKey(search.get("report"));
  const [candidate, setCandidate] = useState<CandidateRecord | null>(null);
  const [quiz, setQuiz] = useState<RecruiterQuiz | null>(null);
  const [assessment, setAssessment] = useState<MasterAssessment | null>(null);
  const [claims, setClaims] = useState<ClaimVerification | null>(null);
  const [score, setScore] = useState<InterviewScore | null>(null);
  const [quality, setQuality] = useState<InterviewQuality | null>(null);
  const [analysis, setAnalysis] = useState<InterviewAnalysis | null>(null);
  const [analysisStatus, setAnalysisStatus] = useState<"ready" | "pending" | "failed" | "missing">("missing");
  const [analysisNote, setAnalysisNote] = useState("");
  const [message, setMessage] = useState("");
  const assessmentStamp = useRef("");
  const [joining, setJoining] = useState(false);
  const [building, setBuilding] = useState(false);
  const [checking, setChecking] = useState(false);
  const [scoring, setScoring] = useState(false);
  const [reviewing, setReviewing] = useState(false);

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
          setBuilding(true);
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
          setBuilding(true);
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
  }, [params.candidateId]);

  useEffect(() => {
    assessmentStamp.current = assessment?.created_at ?? "";
  }, [assessment]);

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

  useEffect(() => {
    if (!building) {
      return;
    }
    const before = assessmentStamp.current;
    const deadline = Date.now() + 4 * 60 * 1000;
    let stopped = false;
    const timer = window.setInterval(() => {
      if (Date.now() > deadline) {
        setMessage("The master assessment is still being written. It will appear on this page when it finishes.");
        setBuilding(false);
        return;
      }
      void apiRequest<MasterAssessment>(`/api/v1/candidates/${params.candidateId}/assessment`)
        .then((next) => {
          if (stopped || next.run_state === "running") {
            return;
          }
          if (next.run_state === "failed") {
            setMessage(next.run_message || "The master assessment could not be built.");
            setAssessment(next);
            setBuilding(false);
            return;
          }
          if (!before || next.created_at !== before) {
            setAssessment(next);
            setBuilding(false);
          }
        })
        .catch((error: unknown) => {
          if (stopped) {
            return;
          }
          if (error instanceof ApiError && (error.code === "ASSESSMENT_PENDING" || error.code === "ASSESSMENT_NOT_FOUND")) {
            return;
          }
          if (error instanceof ApiError && error.code === "ASSESSMENT_FAILED") {
            setMessage(error.message);
            setBuilding(false);
            return;
          }
          if (!(error instanceof ApiError)) {
            return;
          }
          setMessage(error.message);
          setBuilding(false);
        });
    }, 2000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [building, params.candidateId]);

  function openReport(key: string) {
    router.replace(`/candidates/${params.candidateId}?report=${key}`);
  }

  async function buildAssessment() {
    setMessage("");
    setBuilding(true);
    try {
      await apiRequest<AssessmentRun>(`/api/v1/candidates/${params.candidateId}/assessment`, {
        method: "POST",
      });
    } catch (error: unknown) {
      setBuilding(false);
      setMessage(error instanceof Error ? error.message : "The master assessment could not be built.");
    }
  }

  async function rerunAnalysis() {
    setAnalysisNote("");
    setAnalysisStatus("pending");
    try {
      const run = await apiRequest<AnalysisRun>(`/api/v1/candidates/${params.candidateId}/interview-analysis`, {
        method: "POST",
      });
      if (run.state === "ready") {
        const row = await apiRequest<InterviewAnalysis>(`/api/v1/candidates/${params.candidateId}/interview-analysis`);
        setAnalysis(row);
        setAnalysisStatus("ready");
      }
    } catch (error: unknown) {
      setAnalysisStatus("failed");
      setAnalysisNote(error instanceof Error ? error.message : "The question and answer analysis did not finish.");
    }
  }

  async function checkClaims() {
    setChecking(true);
    setMessage("");
    try {
      const checked = await apiRequest<ClaimVerification>(`/api/v1/candidates/${params.candidateId}/claim-verification`, {
        method: "POST",
      });
      setClaims(checked);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The CV claims could not be checked.");
    } finally {
      setChecking(false);
    }
  }

  async function scoreInterview() {
    setScoring(true);
    setMessage("");
    try {
      const scored = await apiRequest<InterviewScore>(`/api/v1/candidates/${params.candidateId}/interview-score`, {
        method: "POST",
      });
      setScore(scored);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The interview could not be scored.");
    } finally {
      setScoring(false);
    }
  }

  async function reviewInterview() {
    setReviewing(true);
    setMessage("");
    try {
      const reviewed = await apiRequest<InterviewQuality>(`/api/v1/candidates/${params.candidateId}/interview-quality`, {
        method: "POST",
      });
      setQuality(reviewed);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The interview could not be reviewed.");
    } finally {
      setReviewing(false);
    }
  }

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

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-8">
        <Link href="/candidates" className="text-sm text-mist hover:text-ivory">
          All candidates
        </Link>
        {message ? <p className="text-sm text-mist">{message}</p> : null}
        {candidate ? (
          <article id="person" className="space-y-6">
            <header className="space-y-3">
              <PageHeader
                eyebrow={candidate.rank ? `Rank ${candidate.rank}` : "Unranked"}
                title={candidate.full_name || "Unnamed"}
              />
              <p className="text-mist">{candidate.email}</p>
              <p className="text-mist">Applied for {candidate.job_title || "an unpublished job"}</p>
              {candidate.scheduled_label ? (
                <p className="text-ivory">Interview scheduled for {candidate.scheduled_label}.</p>
              ) : null}
              <p className="text-mist">
                {candidate.aggregate_score !== null ? `CV score ${candidate.aggregate_score.toFixed(2)}` : "No CV score"}
                {score ? ` · Interview ${score.overall_score.toFixed(1)}` : ""}
                {quiz?.status === "submitted" && quiz.score !== null ? ` · Quiz ${quiz.score} / 100` : ""}
                {candidate.invited ? " · invited" : ""}
              </p>
              {candidate.invited ? (
                <button type="button" onClick={() => void joinInterview()} disabled={joining} className={buttonClass()}>
                  Open interview
                </button>
              ) : null}
            </header>
            <div className="flex flex-wrap gap-2">
              {REPORTS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => openReport(item.key)}
                  className={buttonClass(selected === item.key ? "primary" : "secondary")}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <CandidateReport
              selected={selected}
              score={score}
              scoring={scoring}
              onScore={() => void scoreInterview()}
              quality={quality}
              reviewing={reviewing}
              onReview={() => void reviewInterview()}
              analysis={analysis}
              analysisStatus={analysisStatus}
              analysisNote={analysisNote}
              onRerunAnalysis={() => void rerunAnalysis()}
              claims={claims}
              checking={checking}
              onCheckClaims={() => void checkClaims()}
              assessment={assessment}
              building={building}
              onBuildAssessment={() => void buildAssessment()}
              onDownloadAssessment={() =>
                void downloadAssessmentReport(candidate.id).catch((error: unknown) => {
                  setMessage(error instanceof Error ? error.message : "The report could not be downloaded.");
                })
              }
              quiz={quiz}
              evaluations={candidate.evaluations}
            />
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
