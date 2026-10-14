"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/ui/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
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
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-8">
        <PageHeader eyebrow="Careers" title="Open roles" />
        {message ? <p className="text-sm text-mist">{message}</p> : null}
        <ul className="space-y-3">
          {jobs.map((job) => (
            <li key={job.version_id}>
              <Panel>
                <div className="px-4 py-3">
                  <Link href={`/careers/${job.version_id}`} className="font-display text-2xl font-medium text-ivory hover:text-amber">
                    {job.title}
                  </Link>
                  <p className="text-sm text-mist">
                    {job.seniority} · {job.contract} · {job.company_name}
                  </p>
                </div>
              </Panel>
            </li>
          ))}
        </ul>
      </div>
    </AppShell>
  );
}
