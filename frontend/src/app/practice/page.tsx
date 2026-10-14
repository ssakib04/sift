"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { fieldClass } from "@/components/ui/field";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { PracticeInterview, apiRequest, rememberInterview, rememberPracticeLink } from "@/lib/api";

export default function PracticePage() {
  const router = useRouter();
  const [guestUrl, setGuestUrl] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  async function createRoom() {
    setBusy(true);
    setMessage("");
    setCopied(false);
    try {
      const opened = await apiRequest<PracticeInterview>("/api/v1/interview-sessions/practice", { method: "POST" });
      rememberInterview(opened.session_id, opened.token, opened.role);
      rememberPracticeLink(opened.session_id, opened.guest_url);
      setSessionId(opened.session_id);
      setToken(opened.token);
      setGuestUrl(opened.guest_url);
    } catch (error: unknown) {
      setMessage(error instanceof Error ? error.message : "The practice room could not be opened.");
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(guestUrl);
      setCopied(true);
    } catch {
      setCopied(false);
      setMessage("Select the link and copy it.");
    }
  }

  function enterAsInterviewer() {
    if (!sessionId || !token) {
      return;
    }
    router.push(`/interview/${sessionId}`);
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-xl space-y-8">
        <PageHeader
          eyebrow="Practice"
          title="Try a call without a candidate"
          lede="This opens a video room for you as the interviewer and gives you a guest link. Paste that link on another device. The guest agrees, then both of you are in the same call. No job is posted and no email is sent."
        />
        <Panel>
          <div className="space-y-4 p-6">
            {message ? <p className="text-sm text-mist">{message}</p> : null}
            <button type="button" onClick={() => void createRoom()} disabled={busy} className={buttonClass()}>
              {guestUrl ? "Start another practice call" : "Start a practice call"}
            </button>
            {guestUrl ? (
              <section className="space-y-3">
                <label className="block space-y-2 text-sm text-mist" htmlFor="guest-link">
                  Guest link
                  <input id="guest-link" readOnly value={guestUrl} className={fieldClass} />
                </label>
                <div className="flex flex-wrap gap-3">
                  <button type="button" onClick={() => void copyLink()} className={buttonClass("secondary")}>
                    {copied ? "Copied" : "Copy guest link"}
                  </button>
                  <button type="button" onClick={enterAsInterviewer} className={buttonClass()}>
                    Enter as interviewer
                  </button>
                </div>
              </section>
            ) : null}
          </div>
        </Panel>
      </div>
    </AppShell>
  );
}
