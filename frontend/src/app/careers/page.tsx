"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { SectionLinks } from "@/components/section-links";
import { PublicJob, apiRequest } from "@/lib/api";

export default function CareersPage() {
  const [jobs, setJobs] = useState<PublicJob[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    apiRequest<PublicJob[]>("/api/v1/careers")
      .then(setJobs)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "Could not load jobs.");
      });
  }, []);

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-3xl space-y-8">
        <SectionLinks />
        <header className="space-y-2">
          <p className="text-sm uppercase tracking-[0.2em] text-slate-400">Careers</p>
          <h1 className="text-3xl font-semibold">Open roles</h1>
        </header>
        {message ? <p className="text-sm text-slate-300">{message}</p> : null}
        <ul className="space-y-3">
          {jobs.map((job) => (
            <li key={job.version_id} className="rounded-xl border border-slate-800 px-4 py-3">
              <Link href={`/careers/${job.version_id}`} className="text-lg font-medium hover:underline">
                {job.title}
              </Link>
              <p className="text-sm text-slate-400">
                {job.seniority} · {job.contract} · {job.company_name}
              </p>
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}
