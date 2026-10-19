"use client";

import Link from "next/link";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { CandidateGroup, JobComparison, apiRequest } from "@/lib/api";

function points(value: number | null): string {
  return value === null ? "—" : value.toFixed(1);
}

function CandidatesPageContent() {
  const requestedJobId = useSearchParams().get("job");
  const [groups, setGroups] = useState<CandidateGroup[]>([]);
  const [comparisons, setComparisons] = useState<JobComparison[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    apiRequest<CandidateGroup[]>("/api/v1/candidates")
      .then(setGroups)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Could not load candidates.");
      });
    apiRequest<JobComparison[]>("/api/v1/assessments")
      .then(setComparisons)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Could not load assessments.");
      });
  }, []);

  useEffect(() => {
    if (!requestedJobId || groups.length === 0) {
      return;
    }
    if (!groups.some((group) => group.job_id === requestedJobId)) {
      setMessage("That role has no applicants to rank yet.");
      return;
    }
    document.getElementById(`role-${requestedJobId}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [requestedJobId, groups]);

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl space-y-8">
        <PageHeader eyebrow="Candidates" title="Assessed applicants" />
        {message ? <p className="text-sm text-mist">{message}</p> : null}
        {groups.length === 0 && !message ? <p className="text-sm text-mist">No candidates yet.</p> : null}
        {groups.map((group) => {
          const comparison = comparisons.find((item) => item.job_id === group.job_id);
          return (
          <section
            key={group.job_id}
            id={`role-${group.job_id}`}
            className={`scroll-mt-8 space-y-3 ${requestedJobId === group.job_id ? "rounded-card ring-1 ring-amber/60" : ""}`}
          >
            <h2 className="font-display text-2xl font-medium text-ivory">{group.job_title}</h2>
            {comparison ? (
              <Panel>
                <div className="overflow-x-auto px-4 py-3">
                  <p className="mb-3 text-sm text-mist">
                    Master score · CV {Math.round(comparison.cv_weight * 100)}% · Quiz {Math.round(comparison.mcq_weight * 100)}% ·
                    Interview {Math.round(comparison.interview_weight * 100)}%
                  </p>
                  <table className="w-full min-w-[760px] text-left text-sm">
                    <thead className="text-mist">
                      <tr>
                        <th className="py-2 pr-3 font-semibold">Candidate</th>
                        <th className="py-2 pr-3 font-semibold">Overall</th>
                        <th className="py-2 pr-3 font-semibold">Suitability</th>
                        <th className="py-2 pr-3 font-semibold">Technical</th>
                        <th className="py-2 pr-3 font-semibold">Experience</th>
                        <th className="py-2 pr-3 font-semibold">Qualification</th>
                        <th className="py-2 pr-3 font-semibold">MCQ</th>
                        <th className="py-2 pr-3 font-semibold">Interview Q&A</th>
                        <th className="py-2 font-semibold">Key gap</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparison.rows.map((row) => (
                        <tr key={row.candidate_id} className="border-t border-ivory/10">
                          <td className="py-2 pr-3">
                            <Link href={`/candidates/${row.candidate_id}`} className="font-medium text-ivory hover:text-amber">
                              {row.full_name || "Unnamed"}
                            </Link>
                          </td>
                          <td className="py-2 pr-3 text-ivory">{points(row.overall_score)}</td>
                          <td className="py-2 pr-3 text-ivory">{row.suitability_label || "—"}</td>
                          <td className="py-2 pr-3 text-mist">{points(row.technical_dimension)}</td>
                          <td className="py-2 pr-3 text-mist">{points(row.experience_dimension)}</td>
                          <td className="py-2 pr-3 text-mist">{points(row.qualification_dimension)}</td>
                          <td className="py-2 pr-3 text-mist">{points(row.mcq_score)}</td>
                          <td className="py-2 pr-3 text-mist">{points(row.interview_qa)}</td>
                          <td className="max-w-xs py-2 text-mist">{row.key_gap}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            ) : null}
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
                        {candidate.mcq_score !== null ? ` · Quiz ${candidate.mcq_score}` : ""}
                        {candidate.invited ? " · invited" : ""}
                        {` · ${candidate.parse_status}`}
                      </p>
                    </div>
                  </Panel>
                </li>
              ))}
            </ul>
          </section>
          );
        })}
      </div>
    </AppShell>
  );
}

export default function CandidatesPage() {
  return (
    <Suspense fallback={<AppShell><p className="text-sm text-mist">Opening candidates…</p></AppShell>}>
      <CandidatesPageContent />
    </Suspense>
  );
}
