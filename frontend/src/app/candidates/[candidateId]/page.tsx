"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import { SectionLinks } from "@/components/section-links";
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
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-3xl space-y-8">
        <SectionLinks />
        <Link href="/candidates" className="text-sm text-slate-400 hover:text-white">
          All candidates
        </Link>
        {message ? <p className="text-sm text-slate-300">{message}</p> : null}
        {candidate ? (
          <article className="space-y-6">
            <header className="space-y-2">
              <p className="text-sm uppercase tracking-[0.2em] text-slate-400">
                {candidate.rank ? `Rank ${candidate.rank}` : "Unranked"}
              </p>
              <h1 className="text-3xl font-semibold">{candidate.full_name || "Unnamed"}</h1>
              <p className="text-slate-300">{candidate.email}</p>
              <p className="text-slate-300">Applied for {candidate.job_title || "an unpublished job"}</p>
              <p className="text-slate-400">
                {candidate.aggregate_score !== null ? `Score ${candidate.aggregate_score.toFixed(2)}` : "No score"}
                {candidate.invited ? " · invited" : ""}
              </p>
              {candidate.invited ? (
                <button
                  type="button"
                  onClick={() => void joinInterview()}
                  disabled={joining}
                  className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-60"
                >
                  Open interview
                </button>
              ) : null}
            </header>
            <section className="space-y-3">
              <h2 className="text-lg font-medium">Checklist</h2>
              <ul className="space-y-2">
                {candidate.evaluations.map((item) => (
                  <li key={item.query_id} className="rounded-xl border border-slate-800 px-4 py-3 text-sm space-y-1">
                    <p className="font-medium">
                      {item.query_id} · {item.status.replaceAll("_", " ")}
                    </p>
                    {item.question ? <p className="text-slate-200">{item.question}</p> : null}
                    {item.evidence ? <p className="text-slate-400">{item.evidence}</p> : null}
                  </li>
                ))}
              </ul>
            </section>
          </article>
        ) : null}
      </div>
    </main>
  );
}
