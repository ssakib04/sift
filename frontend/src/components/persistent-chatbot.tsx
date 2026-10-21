"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import { ApiError, CopilotChip, CopilotTurn, JobRecord, apiRequest, downloadAssessmentReport } from "@/lib/api";

type ChatLine = {
  role: "user" | "assistant";
  content: string;
  job?: JobRecord | null;
  chips?: CopilotChip[];
};

function safePath(href: string): string {
  if (href.startsWith("/") && !href.startsWith("//")) {
    return href;
  }
  return "";
}

export function PersistentChatbot() {
  const pathname = usePathname();
  const router = useRouter();
  const scroller = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<ChatLine[]>([
    {
      role: "assistant",
      content:
        "Ask me to draft a job, rank applicants for a role, or open someone on the board. Checklist approval stays a button.",
    },
  ]);

  useEffect(() => {
    const node = scroller.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [lines, busy, open]);

  if (
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/invite/") ||
    pathname.startsWith("/interview/")
  ) {
    return null;
  }

  async function follow(result: CopilotTurn) {
    const href = result.navigation ? safePath(result.navigation.href) : "";
    if (href) {
      router.push(href);
    }
    if (result.report_candidate_id) {
      try {
        await downloadAssessmentReport(result.report_candidate_id);
      } catch (error) {
        const message = error instanceof ApiError ? error.message : "The report could not be downloaded.";
        setLines((current) => [...current, { role: "assistant", content: message }]);
      }
    }
  }

  async function send(content: string) {
    const history = [...lines.filter((line) => line.role === "user" || line.content.length > 0), { role: "user" as const, content }];
    setLines((current) => [...current, { role: "user", content }]);
    setDraft("");
    setBusy(true);
    try {
      const result = await apiRequest<CopilotTurn>("/api/v1/copilot/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history.map((line) => ({ role: line.role, content: line.content })),
        }),
      });
      setLines((current) => [
        ...current,
        { role: "assistant", content: result.message, job: result.job, chips: result.chips },
      ]);
      await follow(result);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "The copilot could not respond.";
      setLines((current) => [...current, { role: "assistant", content: message }]);
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || busy) return;
    await send(content);
  }

  async function onChip(chip: CopilotChip) {
    if (busy) return;
    if (chip.kind === "navigate") {
      const href = safePath(chip.href);
      if (href) router.push(href);
      return;
    }
    if (chip.kind === "report" && chip.candidate_id) {
      try {
        await downloadAssessmentReport(chip.candidate_id);
      } catch (error) {
        const message = error instanceof ApiError ? error.message : "The report could not be downloaded.";
        setLines((current) => [...current, { role: "assistant", content: message }]);
      }
      return;
    }
    const prompt = chip.prompt.trim();
    if (prompt) {
      await send(prompt);
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
        <section className="relative mb-3 flex h-[32rem] w-[24rem] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-card border border-white/15 bg-[linear-gradient(180deg,rgb(92_42_34/0.55),rgb(36_16_14/0.68))] text-ivory shadow-[inset_0_1px_0_rgb(255_228_206/0.4),0_18px_40px_rgb(6_2_2/0.28)] backdrop-blur-xl">
          <header className="flex items-center justify-between border-b border-ivory/10 px-4 py-3">
            <div>
              <p className="text-xs uppercase tracking-[0.16em] text-mist">Copilot</p>
              <h2 className="text-sm font-semibold">Recruiter agent</h2>
            </div>
            <button type="button" onClick={() => setOpen(false)} className="text-sm text-mist">
              Close
            </button>
          </header>
          <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm">
            {lines.map((line, index) => (
              <div key={`${line.role}-${index}`} className={line.role === "user" ? "text-right" : "text-left"}>
                <p className="inline-block max-w-[90%] whitespace-pre-wrap rounded-lg bg-night/60 px-3 py-2 text-left text-ivory">
                  {line.content}
                </p>
                {line.job ? <JobCard job={line.job} busy={busy} onApprove={approve} /> : null}
                {line.chips && line.chips.length > 0 ? (
                  <div className="mt-2 flex max-w-[90%] flex-wrap gap-2">
                    {line.chips.map((chip) => (
                      <button
                        key={`${chip.kind}-${chip.label}`}
                        type="button"
                        disabled={busy}
                        onClick={() => onChip(chip)}
                        className="rounded-control border border-ivory/15 px-2 py-1 text-xs text-ivory disabled:opacity-60"
                      >
                        {chip.label}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
          <form onSubmit={onSubmit} className="flex gap-2 border-t border-ivory/10 p-3">
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Rank candidates for a role..."
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
