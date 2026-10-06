"use client";

import { useEffect, useState } from "react";

import { SectionLinks } from "@/components/section-links";
import { InviteRecord, apiRequest } from "@/lib/api";

export default function InvitePage({ params }: { params: { token: string } }) {
  const [invite, setInvite] = useState<InviteRecord | null>(null);
  const [message, setMessage] = useState("");

  useEffect(() => {
    apiRequest<InviteRecord>(`/api/v1/invites/${params.token}`)
      .then(setInvite)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "This invitation link is not valid.");
      });
  }, [params.token]);

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-xl space-y-6">
        <SectionLinks />
        {message ? <p className="text-sm text-slate-300">{message}</p> : null}
        {invite ? (
          <article className="space-y-3">
            <p className="text-sm uppercase tracking-[0.2em] text-slate-400">{invite.company_name}</p>
            <h1 className="text-3xl font-semibold">You are invited to interview</h1>
            <p className="text-slate-200">Role: {invite.job_title}</p>
            <p className="text-sm text-slate-400">This link is unique to you. The interview room opens in a later step.</p>
          </article>
        ) : null}
      </div>
    </main>
  );
}
