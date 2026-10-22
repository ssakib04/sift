"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";

import { CandidateReport, REPORTS, reportKey } from "@/components/candidate-reports";
import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
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
  const [message, setMessage] = useState("");
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
      .then(setAssessment)
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "ASSESSMENT_NOT_FOUND") {
          setAssessment(null);
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
      .then(setAnalysis)
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.code === "ANALYSIS_NOT_FOUND" || error.code === "CANDIDATE_NOT_FOUND")) {
          setAnalysis(null);
          return;
        }
        setMessage(error instanceof Error ? error.message : "Could not load the question and answer analysis.");
      });
  }, [params.candidateId]);

  function openReport(key: string) {
    router.replace(`/candidates/${params.candidateId}?report=${key}`);
  }

  async function buildAssessment() {
    setBuilding(true);
    setMessage("");
    try {
      const built = await apiRequest<MasterAssessment>(`/api/v1/candidates/${params.candidateId}/assessment`, {
        method: "POST",
      });
      setAssessment(built);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The master assessment could not be built.");
    } finally {
      setBuilding(false);
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
