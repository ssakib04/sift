"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";
import {
  ApiError,
  CandidateRecord,
  ClaimVerification,
  MasterAssessment,
  OpenedInterview,
  RecruiterQuiz,
  apiRequest,
  downloadAssessmentReport,
  rememberInterview,
} from "@/lib/api";

export default function CandidateProfilePage() {
  const params = useParams<{ candidateId: string }>();
  const router = useRouter();
  const [candidate, setCandidate] = useState<CandidateRecord | null>(null);
  const [quiz, setQuiz] = useState<RecruiterQuiz | null>(null);
  const [assessment, setAssessment] = useState<MasterAssessment | null>(null);
  const [claims, setClaims] = useState<ClaimVerification | null>(null);
  const [message, setMessage] = useState("");
  const [joining, setJoining] = useState(false);
  const [building, setBuilding] = useState(false);
  const [checking, setChecking] = useState(false);

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
  }, [params.candidateId]);

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
          <article className="space-y-6">
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
                {candidate.aggregate_score !== null ? `Score ${candidate.aggregate_score.toFixed(2)}` : "No score"}
                {quiz?.status === "submitted" && quiz.score !== null ? ` · Quiz ${quiz.score} / 100` : ""}
                {candidate.invited ? " · invited" : ""}
              </p>
              {candidate.invited ? (
                <button type="button" onClick={() => void joinInterview()} disabled={joining} className={buttonClass()}>
                  Open interview
                </button>
              ) : null}
            </header>
            <section className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="font-display text-2xl font-medium text-ivory">Master assessment</h2>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => void buildAssessment()} disabled={building} className={buttonClass()}>
                    {building ? "Building" : assessment ? "Rebuild assessment" : "Build assessment"}
                  </button>
                  {assessment ? (
                    <button
                      type="button"
                      onClick={() => void downloadAssessmentReport(candidate.id).catch((error: unknown) => {
                        setMessage(error instanceof Error ? error.message : "The report could not be downloaded.");
                      })}
                      className={buttonClass("secondary")}
                    >
                      Download report
                    </button>
                  ) : null}
                </div>
              </div>
              {assessment ? (
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <StatusPill
                      label={assessment.suitability_label}
                      tone={
                        assessment.overall_suitability === "strong_fit"
                          ? "locked"
                          : assessment.overall_suitability === "moderate_fit"
                            ? "draft"
                            : assessment.overall_suitability === "unsuited"
                              ? "attention"
                              : "neutral"
                      }
                    />
                    <p className="text-sm text-ivory">
                      {assessment.overall_score !== null ? `Overall ${assessment.overall_score.toFixed(1)}` : "Overall not calculated"}
                    </p>
                    <p className="text-sm text-mist">
                      CV {Math.round(assessment.cv_weight * 100)}% · Quiz {Math.round(assessment.mcq_weight * 100)}% · Interview{" "}
                      {Math.round(assessment.interview_weight * 100)}%
                    </p>
                  </div>
                  <Panel>
                    <dl className="grid gap-2 px-4 py-3 text-sm sm:grid-cols-3">
                      <div>
                        <dt className="text-mist">CV screening</dt>
                        <dd className="text-ivory">{assessment.component_scores.cv_screening?.toFixed(1) ?? "—"}</dd>
                      </div>
                      <div>
                        <dt className="text-mist">MCQ quiz</dt>
                        <dd className="text-ivory">{assessment.component_scores.mcq_quiz?.toFixed(1) ?? "—"}</dd>
                      </div>
                      <div>
                        <dt className="text-mist">Interview Q&A</dt>
                        <dd className="text-ivory">{assessment.component_scores.interview_qa?.toFixed(1) ?? "—"}</dd>
                      </div>
                    </dl>
                  </Panel>
                  <p className="text-sm leading-6 text-ivory">{assessment.narrative}</p>
                  {assessment.strengths.length ? (
                    <div>
                      <h3 className="text-sm font-semibold text-ivory">Strengths</h3>
                      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-mist">
                        {assessment.strengths.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {assessment.weaknesses.length ? (
                    <div>
                      <h3 className="text-sm font-semibold text-ivory">Weaknesses</h3>
                      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-mist">
                        {assessment.weaknesses.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {assessment.evidence_gaps.length ? (
                    <div>
                      <h3 className="text-sm font-semibold text-ivory">Evidence gaps</h3>
                      <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-mist">
                        {assessment.evidence_gaps.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {assessment.traceability.length ? (
                    <ul className="space-y-2">
                      {assessment.traceability.map((item) => (
                        <li key={`${item.source_type}-${item.source_reference}`}>
                          <Panel>
                            <div className="space-y-1 px-4 py-3 text-sm">
                              <p className="font-medium text-ivory">{item.claim}</p>
                              <p className="text-mist">
                                {item.source_type} · {item.source_reference}
                              </p>
                              <p className="text-mist">{item.evidence}</p>
                            </div>
                          </Panel>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              ) : (
                <p className="text-sm text-mist">
                  Build the report from the CV screening snapshot, the submitted quiz score, and the post-call Q&A analysis.
                </p>
              )}
            </section>
            <section className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="font-display text-2xl font-medium text-ivory">CV follow-up</h2>
                <button type="button" onClick={() => void checkClaims()} disabled={checking} className={buttonClass("secondary")}>
                  {checking ? "Checking" : "Check CV claims"}
                </button>
              </div>
              <p className="text-sm text-mist">
                Prompts for a follow-up conversation. A prompt asks for more detail. It does not reject the candidate or change the score.
              </p>
              {claims ? (
                <div className="space-y-4">
                  {claims.supported_count > 0 ? (
                    <p className="text-sm text-ivory">
                      {claims.supported_count} CV {claims.supported_count === 1 ? "claim matches" : "claims match"} what the candidate said.
                    </p>
                  ) : null}
                  {claims.flags.length ? (
                    (["contradiction", "unverified", "not_discussed"] as const).map((status) => {
                      const group = claims.flags.filter((flag) => flag.status === status);
                      if (!group.length) {
                        return null;
                      }
                      const title =
                        status === "contradiction" ? "Contradiction" : status === "unverified" ? "Unverified" : "Not discussed";
                      const tone = status === "contradiction" ? "attention" : status === "unverified" ? "draft" : "neutral";
                      return (
                        <div key={status} className="space-y-2">
                          <StatusPill label={title} tone={tone} />
                          <ul className="space-y-2">
                            {group.map((flag) => (
                              <li key={flag.claim_id}>
                                <Panel>
                                  <div className="space-y-1 px-4 py-3 text-sm">
                                    <p className="font-medium text-ivory">{flag.follow_up}</p>
                                    <p className="text-mist">{flag.statement}</p>
                                    {flag.cv_quote ? <p className="text-mist">CV: {flag.cv_quote}</p> : null}
                                    {flag.interview_quote ? <p className="text-mist">Interview: {flag.interview_quote}</p> : null}
                                  </div>
                                </Panel>
                              </li>
                            ))}
                          </ul>
                        </div>
                      );
                    })
                  ) : (
                    <p className="text-sm text-mist">No follow-up prompts. The checked CV claims did not leave a contradiction, an unverified claim, or a claim the interview never reached.</p>
                  )}
                </div>
              ) : (
                <p className="text-sm text-mist">Follow-up prompts appear after the interview ends. Check CV claims once the transcript is ready.</p>
              )}
            </section>
            <section className="space-y-3">
              <h2 className="font-display text-2xl font-medium text-ivory">Skill quiz</h2>
              {quiz?.status === "submitted" && quiz.score !== null ? (
                <div className="space-y-2">
                  <p className="text-sm text-ivory">Score {quiz.score} / 100</p>
                  <ul className="space-y-2">
                    {quiz.review.map((item) => (
                      <li key={item.question_id}>
                        <Panel>
                          <div className="space-y-1 px-4 py-3 text-sm">
                            <p className="font-medium text-ivory">{item.prompt}</p>
                            <p className="text-mist">
                              {item.correct ? "Correct" : "Incorrect"}
                              {item.selected_index !== null && item.options[item.selected_index]
                                ? ` · ${item.options[item.selected_index]}`
                                : " · no answer"}
                            </p>
                            <p className="text-mist">{item.explanation}</p>
                          </div>
                        </Panel>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="text-sm text-mist">
                  {quiz?.status === "in_progress" ? "The skill quiz is in progress." : "No skill quiz yet."}
                </p>
              )}
            </section>
            <section className="space-y-3">
              <h2 className="font-display text-2xl font-medium text-ivory">Checklist</h2>
              <ul className="space-y-2">
                {candidate.evaluations.map((item) => (
                  <li key={item.query_id}>
                    <Panel>
                      <div className="space-y-1 px-4 py-3 text-sm">
                        <p className="font-medium text-ivory">
                          {item.query_id} · {item.status.replaceAll("_", " ")}
                        </p>
                        {item.question ? <p className="text-ivory">{item.question}</p> : null}
                        {item.evidence ? <p className="text-mist">{item.evidence}</p> : null}
                      </div>
                    </Panel>
                  </li>
                ))}
              </ul>
            </section>
          </article>
        ) : null}
      </div>
    </AppShell>
  );
}
