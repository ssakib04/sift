"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/ui/app-shell";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { RoleInterviews, apiRequest } from "@/lib/api";

export default function InterviewsPage() {
  const [roles, setRoles] = useState<RoleInterviews[] | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    apiRequest<RoleInterviews[]>("/api/v1/interviews")
      .then(setRoles)
      .catch((error: unknown) => {
        setRoles([]);
        setMessage(error instanceof Error ? error.message : "Could not load interviews.");
      });
  }, []);

  return (
    <AppShell>
      <div id="interviews" className="mx-auto max-w-6xl space-y-8">
        <PageHeader
          eyebrow="Interviews"
          title="Scheduled calls"
          lede="Each role listed here already has an interview on the calendar."
        />
        {message ? <p className="text-sm text-mist">{message}</p> : null}
        {roles === null && !message ? <p className="text-sm text-mist">Opening interviews…</p> : null}
        {roles !== null && roles.length === 0 && !message ? (
          <EmptyState
            title="No interviews scheduled"
            detail="A role appears here once someone on that role has an interview time."
            actionHref="/candidates"
            actionLabel="Open candidates"
          />
        ) : null}
        {roles?.map((role) => (
          <section key={role.job_id} className="space-y-3">
            <div className="flex items-baseline justify-between gap-4">
              <h2 className="font-display text-2xl font-medium text-ivory">{role.job_title}</h2>
              <p className="text-sm text-mist">
                {role.interviews.length === 1 ? "1 interview" : `${role.interviews.length} interviews`}
              </p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              {role.interviews.map((interview) => (
                <Panel key={interview.session_id}>
                  <Link href={`/candidates/${interview.candidate_id}`} className="block space-y-1 px-4 py-3 hover:text-amber">
                    <p className="text-sm font-semibold text-peach">{interview.schedule_label}</p>
                    <p className="font-medium text-ivory">{interview.full_name || "Unnamed"}</p>
                    <p className="text-sm text-mist">{interview.status}</p>
                  </Link>
                </Panel>
              ))}
            </div>
          </section>
        ))}
      </div>
    </AppShell>
  );
}
