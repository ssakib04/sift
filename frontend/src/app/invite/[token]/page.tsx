"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { buttonClass } from "@/components/ui/button";
import { GuestFrame } from "@/components/ui/guest-frame";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { InviteRecord, OpenedInterview, apiRequest, bearer, rememberInterview } from "@/lib/api";

export default function InvitePage({ params }: { params: { token: string } }) {
  const router = useRouter();
  const [invite, setInvite] = useState<InviteRecord | null>(null);
  const [message, setMessage] = useState("");
  const [consent, setConsent] = useState(false);
  const [faceConsent, setFaceConsent] = useState(false);
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
        body: JSON.stringify({ consent: true, biometric_consent: faceConsent }),
      });
      rememberInterview(opened.session_id, opened.token, opened.role);
      router.push(`/interview/${opened.session_id}`);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The interview could not be opened.");
      setBusy(false);
    }
  }

  return (
    <GuestFrame>
      <div className="w-full space-y-6">
        {message ? <p className="text-sm text-mist">{message}</p> : null}
        {invite ? (
          <Panel>
            <article className="space-y-4 p-6">
              <PageHeader eyebrow={invite.company_name} title="You are invited to interview" lede={`Role: ${invite.job_title}`} />
              <label className="flex items-start gap-3 text-sm text-mist">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(event) => setConsent(event.target.checked)}
                  className="mt-1"
                />
                I agree to join this video interview and to have the conversation transcribed for the recruiter.
              </label>
              <label className="flex items-start gap-3 text-sm text-mist">
                <input
                  type="checkbox"
                  checked={faceConsent}
                  onChange={(event) => setFaceConsent(event.target.checked)}
                  className="mt-1"
                />
                I agree to a face check. Sift compares a frame from my camera with the photo on my CV and with other
                candidate photos already stored, then tells the interviewer whether I match. If I do not agree, the
                interview still starts and no identity is assumed.
              </label>
              <button type="button" disabled={!consent || busy} onClick={() => void join()} className={buttonClass()}>
                Join interview
              </button>
            </article>
          </Panel>
        ) : null}
      </div>
    </GuestFrame>
  );
}
