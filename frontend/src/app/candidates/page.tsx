"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SectionLinks } from "@/components/section-links";
import { CandidateGroup, apiRequest } from "@/lib/api";

export default function CandidatesPage() {
  const [groups, setGroups] = useState<CandidateGroup[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    apiRequest<CandidateGroup[]>("/api/v1/candidates")
      .then(setGroups)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Could not load candidates.");
      });
  }, []);

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-3xl space-y-8">
        <SectionLinks />
        <header className="space-y-2">
          <p className="text-sm uppercase tracking-[0.2em] text-slate-400">Candidates</p>
          <h1 className="text-3xl font-semibold">Assessed applicants</h1>
        </header>
        {message ? <p className="text-sm text-slate-300">{message}</p> : null}
        {groups.length === 0 && !message ? <p className="text-sm text-slate-400">No candidates yet.</p> : null}
        {groups.map((group) => (
          <section key={group.job_id} className="space-y-3">
            <h2 className="text-xl font-medium">{group.job_title}</h2>
            <p className="text-sm text-slate-400">Subject: {group.mail_subject}</p>
            <ul className="space-y-2">
              {group.candidates.map((candidate) => (
                <li key={candidate.id} className="rounded-xl border border-slate-800 px-4 py-3">
                  <Link href={`/candidates/${candidate.id}`} className="font-medium hover:underline">
                    {candidate.rank ? `#${candidate.rank}` : "Unranked"} · {candidate.full_name || "Unnamed"}
                  </Link>
                  <p className="text-sm text-slate-300">{candidate.email}</p>
                  <p className="text-sm text-slate-400">
                    {candidate.aggregate_score !== null ? `Score ${candidate.aggregate_score.toFixed(2)}` : "No score"}
                    {candidate.invited ? " · invited" : ""}
                    {` · ${candidate.parse_status}`}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </main>
  );
}
