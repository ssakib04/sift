"use client";

import { useEffect, useState } from "react";

import { SectionLinks } from "@/components/section-links";
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
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-3xl space-y-6">
        <SectionLinks />
        {message ? <p className="text-sm text-slate-300">{message}</p> : null}
        {job ? (
          <article className="space-y-4">
            <p className="text-sm uppercase tracking-[0.2em] text-slate-400">{job.company_name}</p>
            <h1 className="text-3xl font-semibold">{job.title}</h1>
            <p className="text-sm text-slate-400">
              {job.seniority} · {job.contract} · {job.company_country} · {job.minimum_years}+ years
            </p>
            <p className="whitespace-pre-wrap leading-7 text-slate-200">{job.description}</p>
            {structuredData ? (
              <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(structuredData) }} />
            ) : null}
          </article>
        ) : null}
      </div>
    </main>
  );
}
