"use client";

import { FormEvent, useState } from "react";
import { usePathname } from "next/navigation";

import { ApiError, JobRecord, apiRequest } from "@/lib/api";

type ChatLine = {
  role: "user" | "assistant";
  content: string;
  job?: JobRecord | null;
};

export function PersistentChatbot() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<ChatLine[]>([
    {
      role: "assistant",
      content: "Ask me to draft a job. I use the same policy workflow as the Jobs page. The checklist stays unlocked until you approve it.",
    },
  ]);

  if (
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/invite/") ||
    pathname.startsWith("/interview/")
  ) {
    return null;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || busy) return;
    const history = [...lines.filter((line) => line.role === "user" || line.content.length > 0), { role: "user" as const, content }];
    setLines((current) => [...current, { role: "user", content }]);
    setDraft("");
    setBusy(true);
    try {
      const result = await apiRequest<{ message: string; job: JobRecord | null }>("/api/v1/copilot/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history.map((line) => ({ role: line.role, content: line.content })),
        }),
      });
      setLines((current) => [...current, { role: "assistant", content: result.message, job: result.job }]);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "The copilot could not respond.";
      setLines((current) => [...current, { role: "assistant", content: message }]);
    } finally {
      setBusy(false);
    }
  }

  async function approve(job: JobRecord) {
    const latest = job.versions[job.versions.length - 1];
    if (!latest || busy) return;
    setBusy(true);
    try {
      const locked = await apiRequest<JobRecord>(`/api/v1/jobs/${job.id}/versions/${latest.version_number}/approve`, {
        method: "POST",
      });
      const posted = locked.versions[locked.versions.length - 1];
      setLines((current) => [
        ...current,
        {
          role: "assistant",
          content: `Checklist locked for ${locked.title}. Posting status: ${posted?.posting_status ?? "unknown"}.${
            posted?.posting_detail?.startsWith("http") ? ` ${posted.posting_detail}` : ""
          }`,
          job: locked,
        },
      ]);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Approval failed.";
      setLines((current) => [...current, { role: "assistant", content: message }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed bottom-5 right-5 z-50">
      {open ? (
        <section className="mb-3 flex h-[28rem] w-[22rem] max-w-[calc(100vw-2.5rem)] flex-col rounded-card border border-ivory/10 bg-night/75 text-ivory shadow-lift backdrop-blur-2xl">
          <header className="flex items-center justify-between border-b border-ivory/10 px-4 py-3">
            <div>
              <p className="text-xs uppercase tracking-[0.16em] text-mist">Copilot</p>
              <h2 className="text-sm font-semibold">Recruiter agent</h2>
            </div>
            <button type="button" onClick={() => setOpen(false)} className="text-sm text-mist">
              Close
            </button>
          </header>
          <div className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
            {lines.map((line, index) => (
              <div key={`${line.role}-${index}`} className={line.role === "user" ? "text-right" : "text-left"}>
                <p className="inline-block max-w-[90%] whitespace-pre-wrap rounded-lg bg-night/60 px-3 py-2 text-left text-ivory">
                  {line.content}
                </p>
                {line.job ? <JobCard job={line.job} busy={busy} onApprove={approve} /> : null}
              </div>
            ))}
          </div>
          <form onSubmit={onSubmit} className="flex gap-2 border-t border-ivory/10 p-3">
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Draft a senior Python role..."
              className="min-w-0 flex-1 rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-sm text-ivory placeholder:text-mist/70"
            />
            <button type="submit" disabled={busy} className="rounded-control bg-action px-3 py-2 text-sm font-semibold text-ivory disabled:opacity-60">
              Send
            </button>
          </form>
        </section>
      ) : null}
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="ml-auto block rounded-full bg-action px-4 py-2 text-sm font-semibold text-ivory shadow-lift"
      >
        Copilot
      </button>
    </div>
  );
}

function JobCard({
  job,
  busy,
  onApprove,
}: {
  job: JobRecord;
  busy: boolean;
  onApprove: (job: JobRecord) => void;
}) {
  const latest = job.versions[job.versions.length - 1];
  if (!latest) return null;
  return (
    <div className="mt-2 max-w-[90%] rounded-lg border border-ivory/10 px-3 py-2 text-left text-xs text-mist">
      <p>
        {job.title} · v{latest.version_number} · {latest.status}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <a href={`/jobs?job=${job.id}`} className="rounded-control border border-ivory/15 px-2 py-1 text-ivory">
          Review draft
        </a>
        {latest.status === "draft" ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => onApprove(job)}
            className="rounded-control bg-action px-2 py-1 text-ivory disabled:opacity-60"
          >
            Approve and post
          </button>
        ) : null}
      </div>
    </div>
  );
}
