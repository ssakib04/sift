import { buttonClass } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";
import {
  CandidateEvaluation,
  ClaimVerification,
  InterviewAnalysis,
  InterviewQuality,
  InterviewScore,
  MasterAssessment,
  RecruiterQuiz,
  TranscriptTurn,
} from "@/lib/api";

export const REPORTS = [
  { key: "transcript", label: "Transcript" },
  { key: "score", label: "Interview score" },
  { key: "quality", label: "Interview quality" },
  { key: "qa", label: "Q&A analysis" },
  { key: "claims", label: "CV claims" },
  { key: "assessment", label: "Master assessment" },
  { key: "quiz", label: "Skill quiz" },
  { key: "checklist", label: "CV checklist" },
] as const;

export type ReportKey = (typeof REPORTS)[number]["key"];

export function reportKey(value: string | null): ReportKey | "" {
  if (REPORTS.some((item) => item.key === value)) {
    return value as ReportKey;
  }
  return "";
}

export function CandidateReport({
  selected,
  progress,
  onRetry,
  score,
  quality,
  analysis,
  analysisStatus,
  analysisNote,
  claims,
  assessment,
  onDownloadAssessment,
  quiz,
  evaluations,
  ended,
  turns,
  candidateName,
}: {
  selected: ReportKey;
  progress: Record<string, string>;
  onRetry: () => void;
  score: InterviewScore | null;
  quality: InterviewQuality | null;
  analysis: InterviewAnalysis | null;
  analysisStatus: "ready" | "pending" | "failed" | "missing";
  analysisNote: string;
  claims: ClaimVerification | null;
  assessment: MasterAssessment | null;
  onDownloadAssessment: () => void;
  quiz: RecruiterQuiz | null;
  evaluations: CandidateEvaluation[];
  ended: boolean;
  turns: TranscriptTurn[];
  candidateName: string;
}) {
  if (selected === "transcript") {
    return <TranscriptReport turns={turns} candidateName={candidateName} />;
  }
  if (selected === "score") {
    return <ScoreReport score={score} phase={progress.score || ""} onRetry={onRetry} ended={ended} />;
  }
  if (selected === "quality") {
    return <QualityReport quality={quality} phase={progress.quality || ""} onRetry={onRetry} ended={ended} />;
  }
  if (selected === "qa") {
    return <QaReport analysis={analysis} status={progress.qa === "pending" ? "pending" : progress.qa === "failed" ? "failed" : analysisStatus} note={analysisNote} onRetry={onRetry} ended={ended} />;
  }
  if (selected === "claims") {
    return <ClaimsReport claims={claims} phase={progress.claims || ""} onRetry={onRetry} ended={ended} />;
  }
  if (selected === "assessment") {
    return (
      <AssessmentReport
        assessment={assessment}
        phase={progress.assessment || ""}
        onRetry={onRetry}
        onDownloadAssessment={onDownloadAssessment}
        ended={ended}
      />
    );
  }
  if (selected === "quiz") {
    return <QuizReport quiz={quiz} />;
  }
  return <ChecklistReport evaluations={evaluations} />;
}

function speakerLabel(speaker: string, candidateName: string): string {
  if (speaker === "candidate") {
    return candidateName.trim() || "Candidate";
  }
  if (speaker === "recruiter") {
    return "Recruiter";
  }
  return speaker;
}

function TranscriptReport({ turns, candidateName }: { turns: TranscriptTurn[]; candidateName: string }) {
  return (
    <section className="space-y-4">
      <h2 className="font-display text-3xl font-medium text-ivory">Transcript</h2>
      <p className="text-base leading-7 text-mist">What was said in this candidate's interview.</p>
      {turns.length === 0 ? (
        <p className="text-base leading-7 text-ivory">No interview transcript yet.</p>
      ) : (
        <ol className="space-y-5">
          {turns.map((turn) => (
            <li key={turn.id} className="space-y-1">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-mist">{speakerLabel(turn.speaker, candidateName)}</p>
              <p className="text-base leading-7 text-ivory">{turn.text}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function waitingCopy(phase: string, writing: string, failed: string, idle: string): string {
  if (phase === "pending") {
    return writing;
  }
  if (phase === "failed") {
    return failed;
  }
  return idle;
}

function ScoreReport({ score, phase, onRetry, ended }: { score: InterviewScore | null; phase: string; onRetry: () => void; ended: boolean }) {
  return (
    <section className="space-y-4">
      <h2 className="font-display text-3xl font-medium text-ivory">Interview score</h2>
      <p className="text-base leading-7 text-mist">This score uses only the interview. It is separate from the CV score.</p>
      {score ? (
        <div className="space-y-4">
          <p className="font-display text-4xl text-ivory">{score.overall_score.toFixed(1)}</p>
          <p className="text-base leading-7 text-ivory">{score.summary}</p>
          <ul className="space-y-2">
            {score.dimensions.map((item) => (
              <li key={item.key}>
                <Panel>
                  <div className="space-y-1 px-4 py-3 text-base leading-7">
                    <p className="font-medium text-ivory">
                      {item.label} · {item.score.toFixed(1)}
                    </p>
                    <p className="text-mist">{item.note}</p>
                    {item.evidence ? <p className="text-ivory">“{item.evidence}”</p> : null}
                  </div>
                </Panel>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-base leading-7 text-mist">
            {waitingCopy(phase, "Writing the interview score.", "The interview score could not be written.", ended ? "This part was not written." : "The interview score appears after the interview ends.")}
          </p>
          {phase === "failed" ? (
            <button type="button" onClick={onRetry} className={buttonClass("secondary")}>
              Try again
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}

function QualityReport({ quality, phase, onRetry, ended }: { quality: InterviewQuality | null; phase: string; onRetry: () => void; ended: boolean }) {
  return (
    <section className="space-y-4">
      <h2 className="font-display text-3xl font-medium text-ivory">Interview quality</h2>
      <p className="text-base leading-7 text-mist">This report is about how the interview was run. It does not score the candidate.</p>
      {quality ? (
        <div className="space-y-3">
          <p className="text-base leading-7 text-ivory">Process quality {quality.overall_score.toFixed(1)} / 100</p>
          <p className="text-base leading-7 text-mist">{quality.summary}</p>
          <p className="text-base leading-7 text-mist">
            Interviewer {Math.round(quality.interviewer_share * 100)}% · Candidate {Math.round(quality.candidate_share * 100)}%
          </p>
          <ul className="space-y-2">
            {quality.dimensions.map((item) => (
              <li key={item.key}>
                <Panel>
                  <div className="space-y-1 px-4 py-3 text-base leading-7">
                    <p className="font-medium text-ivory">
                      {item.label}
                      {item.score === null ? " · Not compared" : ` · ${item.score.toFixed(1)}`}
                    </p>
                    <p className="text-mist">{item.note}</p>
                  </div>
                </Panel>
              </li>
            ))}
          </ul>
          {quality.recommendations.length ? (
            <div className="space-y-2">
              <h3 className="text-base font-semibold text-ivory">Improvements for the next interview</h3>
              <ul className="space-y-2">
                {quality.recommendations.map((item) => (
                  <li key={`${item.kind}-${item.text}`}>
                    <Panel>
                      <div className="space-y-1 px-4 py-3 text-base leading-7">
                        <p className="text-xs uppercase tracking-wide text-mist">{item.kind.replaceAll("_", " ")}</p>
                        <p className="text-ivory">{item.text}</p>
                      </div>
                    </Panel>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-base leading-7 text-mist">No process changes suggested.</p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-base leading-7 text-mist">
            {waitingCopy(
              phase,
              "Writing the process review.",
              "The process review could not be written.",
              ended ? "This part was not written." : "The process review appears after the interview ends.",
            )}
          </p>
          {phase === "failed" ? (
            <button type="button" onClick={onRetry} className={buttonClass("secondary")}>
              Try again
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}

function QaReport({
  analysis,
  status,
  note,
  onRetry,
  ended,
}: {
  analysis: InterviewAnalysis | null;
  status: "ready" | "pending" | "failed" | "missing";
  note: string;
  onRetry: () => void;
  ended: boolean;
}) {
  if (!analysis) {
    const writing = status === "pending";
    const failed = status === "failed";
    return (
      <section className="space-y-3">
        <h2 className="font-display text-3xl font-medium text-ivory">Q&A analysis</h2>
        <p className="text-base leading-7 text-mist">
          {writing
            ? "Writing the question and answer analysis."
            : failed
              ? note || "The question and answer analysis did not finish."
              : ended
                ? "This part was not written."
                : "The question and answer analysis appears after the interview ends."}
        </p>
        {failed ? (
          <button type="button" onClick={onRetry} className={buttonClass("secondary")}>
            Try again
          </button>
        ) : null}
      </section>
    );
  }
  return (
    <section className="space-y-4">
      <h2 className="font-display text-3xl font-medium text-ivory">Q&A analysis</h2>
      <p className="text-base leading-7 text-mist">{analysis.summary}</p>
      <ul className="grid gap-2 text-base leading-7 sm:grid-cols-2">
        <li>
          <Panel>
            <div className="px-4 py-3">Relevance {analysis.relevance.toFixed(1)}</div>
          </Panel>
        </li>
        <li>
          <Panel>
            <div className="px-4 py-3">Technical accuracy {analysis.technical_accuracy.toFixed(1)}</div>
          </Panel>
        </li>
        <li>
          <Panel>
            <div className="px-4 py-3">Completeness {analysis.completeness.toFixed(1)}</div>
          </Panel>
        </li>
        <li>
          <Panel>
            <div className="px-4 py-3">Articulation {analysis.articulation.toFixed(1)}</div>
          </Panel>
        </li>
      </ul>
      {analysis.gaps.length > 0 ? (
        <div>
          <h3 className="text-base font-semibold text-ivory">Coverage gaps</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-base leading-7 text-mist">
            {analysis.gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {analysis.discrepancies.length > 0 ? (
        <div>
          <h3 className="text-base font-semibold text-ivory">Discrepancies</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-base leading-7 text-mist">
            {analysis.discrepancies.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {analysis.pairs.length > 0 ? (
        <ul className="space-y-2">
          {analysis.pairs.map((pair) => (
            <li key={pair.pair_id}>
              <Panel>
                <div className="space-y-1 px-4 py-3 text-base leading-7">
                  <p className="font-medium text-ivory">
                    {pair.pair_id} · {pair.intent.replaceAll("_", " ")}
                  </p>
                  <p className="text-ivory">{pair.question}</p>
                  <p className="text-mist">{pair.answer || "No answer"}</p>
                  <p className="text-mist">{pair.citation}</p>
                  <p className="text-mist">
                    Relevance {pair.relevance.toFixed(1)} · Technical accuracy {pair.technical_accuracy.toFixed(1)} · Completeness{" "}
                    {pair.completeness.toFixed(1)} · Articulation {pair.articulation.toFixed(1)}
                  </p>
                </div>
              </Panel>
            </li>
          ))}
        </ul>
      ) : null}
      {analysis.justifications.length > 0 ? (
        <ul className="space-y-2 text-base leading-7">
          {analysis.justifications.map((item) => (
            <li key={`${item.citation}-${item.claim}`}>
              <p className="text-ivory">{item.claim}</p>
              <p className="text-mist">{item.citation}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function ClaimsReport({ claims, phase, onRetry, ended }: { claims: ClaimVerification | null; phase: string; onRetry: () => void; ended: boolean }) {
  return (
    <section className="space-y-4">
      <h2 className="font-display text-3xl font-medium text-ivory">CV claims</h2>
      <p className="text-base leading-7 text-mist">
        Prompts for a follow-up conversation. A prompt asks for more detail. It does not reject the candidate or change the score.
      </p>
      {claims ? (
        <div className="space-y-4">
          {claims.supported_count > 0 ? (
            <p className="text-base leading-7 text-ivory">
              {claims.supported_count} CV {claims.supported_count === 1 ? "claim matches" : "claims match"} what the candidate said.
            </p>
          ) : null}
          {claims.flags.length ? (
            (["contradiction", "unverified", "not_discussed"] as const).map((status) => {
              const group = claims.flags.filter((flag) => flag.status === status);
              if (!group.length) {
                return null;
              }
              const title = status === "contradiction" ? "Contradiction" : status === "unverified" ? "Unverified" : "Not discussed";
              const tone = status === "contradiction" ? "attention" : status === "unverified" ? "draft" : "neutral";
              return (
                <div key={status} className="space-y-2">
                  <StatusPill label={title} tone={tone} />
                  <ul className="space-y-2">
                    {group.map((flag) => (
                      <li key={flag.claim_id}>
                        <Panel>
                          <div className="space-y-1 px-4 py-3 text-base leading-7">
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
            <p className="text-base leading-7 text-mist">
              No follow-up prompts. The checked CV claims did not leave a contradiction, an unverified claim, or a claim the interview never reached.
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-base leading-7 text-mist">
            {waitingCopy(phase, "Writing the CV claim check.", "The CV claim check could not be written.", ended ? "This part was not written." : "The CV claim check appears after the interview ends.")}
          </p>
          {phase === "failed" ? (
            <button type="button" onClick={onRetry} className={buttonClass("secondary")}>
              Try again
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}

function AssessmentReport({
  assessment,
  phase,
  onRetry,
  onDownloadAssessment,
  ended,
}: {
  assessment: MasterAssessment | null;
  phase: string;
  onRetry: () => void;
  onDownloadAssessment: () => void;
  ended: boolean;
}) {
  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-3xl font-medium text-ivory">Master assessment</h2>
        {assessment ? (
          <button type="button" onClick={onDownloadAssessment} className={buttonClass("secondary")}>
            Download report
          </button>
        ) : null}
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
            <p className="text-base leading-7 text-ivory">
              {assessment.overall_score !== null ? `Overall ${assessment.overall_score.toFixed(1)}` : "Overall not calculated"}
            </p>
            <p className="text-base leading-7 text-mist">
              CV {(assessment.cv_weight * 100).toFixed(1)}% · Interview {(assessment.interview_weight * 100).toFixed(1)}%
            </p>
          </div>
          <Panel>
            <dl className="grid gap-2 px-4 py-3 text-base leading-7 sm:grid-cols-2">
              <div>
                <dt className="text-mist">CV screening</dt>
                <dd className="text-ivory">{assessment.component_scores.cv_screening?.toFixed(1) ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-mist">Interview Q&A</dt>
                <dd className="text-ivory">{assessment.component_scores.interview_qa?.toFixed(1) ?? "—"}</dd>
              </div>
            </dl>
          </Panel>
          <p className="text-base leading-7 text-ivory">{assessment.narrative}</p>
          {assessment.strengths.length ? (
            <div>
              <h3 className="text-base font-semibold text-ivory">Strengths</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-base leading-7 text-mist">
                {assessment.strengths.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {assessment.weaknesses.length ? (
            <div>
              <h3 className="text-base font-semibold text-ivory">Weaknesses</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-base leading-7 text-mist">
                {assessment.weaknesses.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {assessment.evidence_gaps.length ? (
            <div>
              <h3 className="text-base font-semibold text-ivory">Evidence gaps</h3>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-base leading-7 text-mist">
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
                    <div className="space-y-1 px-4 py-3 text-base leading-7">
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
        <div className="space-y-3">
          <p className="text-base leading-7 text-mist">
            {waitingCopy(
              phase,
              "Writing the master assessment. You can leave this page and come back.",
              "The master assessment could not be written.",
              ended ? "This part was not written." : "The master assessment appears after the interview ends.",
            )}
          </p>
          {phase === "failed" ? (
            <button type="button" onClick={onRetry} className={buttonClass("secondary")}>
              Try again
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}

function QuizReport({ quiz }: { quiz: RecruiterQuiz | null }) {
  return (
    <section className="space-y-3">
      <h2 className="font-display text-3xl font-medium text-ivory">Skill quiz</h2>
      {quiz?.status === "submitted" && quiz.score !== null ? (
        <div className="space-y-2">
          <p className="text-base leading-7 text-ivory">Score {quiz.score} / 100</p>
          <ul className="space-y-2">
            {quiz.review.map((item) => (
              <li key={item.question_id}>
                <Panel>
                  <div className="space-y-1 px-4 py-3 text-base leading-7">
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
        <p className="text-base leading-7 text-mist">{quiz?.status === "in_progress" ? "The skill quiz is in progress." : "No skill quiz yet."}</p>
      )}
    </section>
  );
}

function ChecklistReport({ evaluations }: { evaluations: CandidateEvaluation[] }) {
  return (
    <section className="space-y-3">
      <h2 className="font-display text-3xl font-medium text-ivory">CV checklist</h2>
      {evaluations.length ? (
        <ul className="space-y-2">
          {evaluations.map((item) => (
            <li key={item.query_id}>
              <Panel>
                <div className="space-y-1 px-4 py-3 text-base leading-7">
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
      ) : (
        <p className="text-base leading-7 text-mist">No checklist results yet.</p>
      )}
    </section>
  );
}
