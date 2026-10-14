"use client";

import { useEffect, useState } from "react";

import { AppShell } from "@/components/ui/app-shell";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { PublicJob, apiRequest } from "@/lib/api";

export default function CareerDetailPage({ params }: { params: { versionId: string } }) {
  const [job, setJob] = useState<PublicJob | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    apiRequest<PublicJob>(`/api/v1/careers/${params.versionId}`)
      .then(setJob)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "This job is not published.");
      });
  }, [params.versionId]);

  const structuredData = job
    ? {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        title: job.title,
        description: job.description,
        employmentType: job.contract,
        hiringOrganization: { "@type": "Organization", name: job.company_name },
        jobLocation: { "@type": "Place", address: job.company_country },
      }
    : null;

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-6">
        {message ? <p className="text-sm text-mist">{message}</p> : null}
        {job ? (
          <article className="space-y-4">
            <PageHeader eyebrow={job.company_name} title={job.title} />
            <p className="text-sm text-mist">
              {job.seniority} · {job.contract} · {job.company_country} · {job.minimum_years}+ years
            </p>
            <p className="whitespace-pre-wrap leading-7 text-ivory">{job.description}</p>
            <Panel>
              <div className="space-y-2 p-4 text-sm">
                <h2 className="text-base font-medium text-ivory">Apply by email</h2>
                <p>
                  Send your CV as a PDF or DOCX to <span className="text-ivory">{job.apply_email}</span>.
                </p>
                <p>
                  Subject: <span className="text-ivory">{job.apply_subject}</span>
                </p>
                <p className="text-mist">You can also put the job id {job.job_id} in the subject line.</p>
              </div>
            </Panel>
            {structuredData ? (
              <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }} />
            ) : null}
          </article>
        ) : null}
      </div>
    </AppShell>
  );
}
