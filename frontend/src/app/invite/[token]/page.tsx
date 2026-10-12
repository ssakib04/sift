"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { InviteRecord, OpenedInterview, apiRequest, bearer, rememberInterview } from "@/lib/api";

export default function InvitePage({ params }: { params: { token: string } }) {
  const router = useRouter();
  const [invite, setInvite] = useState<InviteRecord | null>(null);
  const [message, setMessage] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiRequest<InviteRecord>(`/api/v1/invites/${params.token}`)
      .then(setInvite)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "This invitation link is not valid.");
      });
  }, [params.token]);

  async function join() {
    setBusy(true);
    setMessage("");
    try {
      const opened = await apiRequest<OpenedInterview>("/api/v1/interview-sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: params.token }),
      });
      await apiRequest(`/api/v1/interview-sessions/${opened.session_id}/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...bearer(opened.token) },
        body: JSON.stringify({ consent: true }),
      });
      rememberInterview(opened.session_id, opened.token, opened.role);
      router.push(`/interview/${opened.session_id}`);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The interview could not be opened.");
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-xl space-y-6">
        {message ? <p className="text-sm text-slate-300">{message}</p> : null}
        {invite ? (
          <article className="space-y-4">
            <p className="text-sm uppercase tracking-[0.2em] text-slate-400">{invite.company_name}</p>
            <h1 className="text-3xl font-semibold">You are invited to interview</h1>
            <p className="text-slate-200">Role: {invite.job_title}</p>
            <label className="flex items-start gap-3 text-sm text-slate-300">
              <input
                type="checkbox"
                checked={consent}
                onChange={(event) => setConsent(event.target.checked)}
                className="mt-1"
              />
              I agree to join this video interview and to have the conversation transcribed for the recruiter.
            </label>
            <button
              type="button"
              disabled={!consent || busy}
              onClick={() => void join()}
              className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-60"
            >
              Join interview
            </button>
          </article>
        ) : null}
      </div>
    </main>
  );
}
