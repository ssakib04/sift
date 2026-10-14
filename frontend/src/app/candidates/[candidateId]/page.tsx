"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { CandidateRecord, OpenedInterview, apiRequest, rememberInterview } from "@/lib/api";

export default function CandidateProfilePage() {
  const params = useParams<{ candidateId: string }>();
  const router = useRouter();
  const [candidate, setCandidate] = useState<CandidateRecord | null>(null);
  const [message, setMessage] = useState("");
  const [joining, setJoining] = useState(false);

  useEffect(() => {
    apiRequest<CandidateRecord>(`/api/v1/candidates/${params.candidateId}`)
      .then(setCandidate)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Could not open this candidate.");
      });
  }, [params.candidateId]);

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
              <p className="text-mist">
                {candidate.aggregate_score !== null ? `Score ${candidate.aggregate_score.toFixed(2)}` : "No score"}
                {candidate.invited ? " · invited" : ""}
              </p>
              {candidate.invited ? (
                <button type="button" onClick={() => void joinInterview()} disabled={joining} className={buttonClass()}>
                  Open interview
                </button>
              ) : null}
            </header>
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
