"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/ui/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
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
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-8">
        <PageHeader eyebrow="Candidates" title="Assessed applicants" />
        {message ? <p className="text-sm text-mist">{message}</p> : null}
        {groups.length === 0 && !message ? <p className="text-sm text-mist">No candidates yet.</p> : null}
        {groups.map((group) => (
          <section key={group.job_id} className="space-y-3">
            <h2 className="font-display text-2xl font-medium text-ivory">{group.job_title}</h2>
            <p className="text-sm text-mist">Subject: {group.mail_subject}</p>
            <ul className="space-y-2">
              {group.candidates.map((candidate) => (
                <li key={candidate.id}>
                  <Panel>
                    <div className="px-4 py-3">
                      <Link href={`/candidates/${candidate.id}`} className="font-medium text-ivory hover:text-amber">
                        {candidate.rank ? `#${candidate.rank}` : "Unranked"} · {candidate.full_name || "Unnamed"}
                      </Link>
                      <p className="text-sm text-mist">{candidate.email}</p>
                      <p className="text-sm text-mist">
                        {candidate.aggregate_score !== null ? `Score ${candidate.aggregate_score.toFixed(2)}` : "No score"}
                        {candidate.invited ? " · invited" : ""}
                        {` · ${candidate.parse_status}`}
                      </p>
                    </div>
                  </Panel>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </AppShell>
  );
}
