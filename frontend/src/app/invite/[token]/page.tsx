"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { FaceLobby } from "@/components/interview/face-lobby";
import { buttonClass } from "@/components/ui/button";
import { GuestFrame } from "@/components/ui/guest-frame";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import {
  Identification,
  IdentificationAck,
  InviteRecord,
  OpenedInterview,
  apiRequest,
  bearer,
  rememberInterview,
} from "@/lib/api";

export default function InvitePage({ params }: { params: { token: string } }) {
  const router = useRouter();
  const [invite, setInvite] = useState<InviteRecord | null>(null);
  const [message, setMessage] = useState("");
  const [consent, setConsent] = useState(false);
  const [faceConsent, setFaceConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [opened, setOpened] = useState<OpenedInterview | null>(null);
  const [phase, setPhase] = useState<"form" | "checking" | "waiting">("form");
  const sendingFrame = useRef(false);
  const joined = useRef(false);

  useEffect(() => {
    apiRequest<InviteRecord>(`/api/v1/invites/${params.token}`)
      .then(setInvite)
      .catch((error: unknown) => {
        setMessage(error instanceof Error ? error.message : "This invitation link is not valid.");
      });
  }, [params.token]);

  const startCall = useCallback(
    async (session: OpenedInterview, biometric: boolean) => {
      if (joined.current) {
        return;
      }
      joined.current = true;
      try {
        await apiRequest(`/api/v1/interview-sessions/${session.session_id}/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...bearer(session.token) },
          body: JSON.stringify({ consent: true, biometric_consent: biometric }),
        });
        rememberInterview(session.session_id, session.token, session.role);
        router.push(`/interview/${session.session_id}`);
      } catch (error: unknown) {
        joined.current = false;
        setMessage(error instanceof Error ? error.message : "The interview could not be opened.");
        setBusy(false);
      }
    },
    [router],
  );

  useEffect(() => {
    if (phase !== "waiting" || !opened) {
      return;
    }
    let stop = false;
    async function poll() {
      if (!opened) {
        return;
      }
      try {
        const next = await apiRequest<Identification>(`/api/v1/interview-sessions/${opened.session_id}/identification`, {
          headers: bearer(opened.token),
        });
        if (stop) {
          return;
        }
        setMessage(next.message);
        if (next.can_join) {
          await startCall(opened, faceConsent);
        }
      } catch (error: unknown) {
        if (!stop) {
          setMessage(error instanceof Error ? error.message : "The face check could not be read.");
        }
      }
    }
    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, 2000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [faceConsent, opened, phase, startCall]);

  async function begin() {
    setBusy(true);
    setMessage("");
    try {
      const session = await apiRequest<OpenedInterview>("/api/v1/interview-sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: params.token }),
      });
      rememberInterview(session.session_id, session.token, session.role);
      if (!invite?.face_check_required) {
        await startCall(session, false);
        return;
      }
      setOpened(session);
      if (faceConsent) {
        await apiRequest(`/api/v1/interview-sessions/${session.session_id}/identification/consent`, {
          method: "POST",
          headers: bearer(session.token),
        });
        setPhase("checking");
      } else {
        setPhase("waiting");
        setMessage("A face check has to match the photo on your CV before you join. A recruiter can still let you in.");
      }
      setBusy(false);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The interview could not be opened.");
      setBusy(false);
    }
  }

  const sendFrame = useCallback(
    async (imageBase64: string) => {
      if (!opened || sendingFrame.current || joined.current || phase !== "checking") {
        return;
      }
      sendingFrame.current = true;
      try {
        const ack = await apiRequest<IdentificationAck>(`/api/v1/interview-sessions/${opened.session_id}/identification`, {
          method: "POST",
          headers: { ...bearer(opened.token), "Content-Type": "application/json" },
          body: JSON.stringify({ image_base64: imageBase64 }),
        });
        if (ack.can_join) {
          await startCall(opened, true);
        } else if (ack.concluded) {
          setPhase("waiting");
        }
      } catch (error: unknown) {
        setMessage(error instanceof Error ? error.message : "The face check could not be completed.");
      } finally {
        sendingFrame.current = false;
      }
    },
    [opened, phase, startCall],
  );

  const faceRequired = Boolean(invite?.face_check_required);

  return (
    <GuestFrame>
      <div className="w-full space-y-6">
        {message ? <p className="text-sm text-mist">{message}</p> : null}
        {invite ? (
          <Panel>
            <article className="space-y-4 p-6">
              <PageHeader
                eyebrow={invite.company_name}
                title="Congratulations"
                lede={`You have been selected to interview for ${invite.job_title}.`}
              />
              {invite.scheduled_label ? (
                <p className="text-sm text-ivory">Your interview is scheduled for {invite.scheduled_label}.</p>
              ) : null}
              {phase === "form" ? (
                <>
                  <label className="flex items-start gap-3 text-sm text-mist">
                    <input
                      type="checkbox"
                      checked={consent}
                      onChange={(event) => setConsent(event.target.checked)}
                      className="mt-1"
                    />
                    I agree to join this video interview and to have the conversation transcribed for the recruiter.
                  </label>
                  {faceRequired ? (
                    <label className="flex items-start gap-3 text-sm text-mist">
                      <input
                        type="checkbox"
                        checked={faceConsent}
                        onChange={(event) => setFaceConsent(event.target.checked)}
                        className="mt-1"
                      />
                      I agree to a face check before I join. Sift compares my camera with the photo on my CV. A match
                      lets me in. If it does not match, or if I do not agree, I wait here until a recruiter lets me in.
                    </label>
                  ) : null}
                  <button type="button" disabled={!consent || busy} onClick={() => void begin()} className={buttonClass()}>
                    {faceRequired ? "Continue" : "Join interview"}
                  </button>
                </>
              ) : null}
              {phase === "checking" ? (
                <FaceLobby
                  active
                  onFrame={(frame) => void sendFrame(frame)}
                  onError={() => {
                    setPhase("waiting");
                    setMessage("The camera could not be opened. A recruiter can still let you in.");
                  }}
                />
              ) : null}
              {phase === "waiting" ? (
                <p className="text-sm text-ivory">Stay on this page. You will join when a recruiter lets you in.</p>
              ) : null}
            </article>
          </Panel>
        ) : null}
      </div>
    </GuestFrame>
  );
}
