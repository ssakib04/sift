"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { SectionLinks } from "@/components/section-links";
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
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-xl space-y-8">
        <SectionLinks />
        <header className="space-y-2">
          <p className="text-sm uppercase tracking-[0.2em] text-slate-400">Practice</p>
          <h1 className="text-3xl font-semibold">Try a call without a candidate</h1>
          <p className="text-slate-300">
            This opens a video room for you as the interviewer and gives you a guest link. Paste that link on another
            device. The guest agrees, then both of you are in the same call. No job is posted and no email is sent.
          </p>
        </header>
        {message ? <p className="text-sm text-slate-300">{message}</p> : null}
        <button
          type="button"
          onClick={() => void createRoom()}
          disabled={busy}
          className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-60"
        >
          {guestUrl ? "Start another practice call" : "Start a practice call"}
        </button>
        {guestUrl ? (
          <section className="space-y-3">
            <label className="block space-y-2 text-sm text-slate-300" htmlFor="guest-link">
              Guest link
              <input
                id="guest-link"
                readOnly
                value={guestUrl}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-slate-100"
              />
            </label>
            <div className="flex flex-wrap gap-3">
              <button type="button" onClick={() => void copyLink()} className="rounded-lg border border-slate-700 px-4 py-2 text-sm">
                {copied ? "Copied" : "Copy guest link"}
              </button>
              <button
                type="button"
                onClick={enterAsInterviewer}
                className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-slate-950"
              >
                Enter as interviewer
              </button>
            </div>
          </section>
        ) : null}
      </div>
    </main>
  );
}
