"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import {
  ApiError,
  CopilotChip,
  CopilotTurn,
  JobRecord,
  apiRequest,
  downloadAssessmentReport,
  rememberInterview,
  rememberPracticeLink,
} from "@/lib/api";

type ChatLine = {
  role: "user" | "assistant";
  content: string;
  reveal?: number;
  job?: JobRecord | null;
  chips?: CopilotChip[];
};

function wordCount(text: string): number {
  const parts = text.match(/\S+/g);
  return parts ? parts.length : 0;
}

function visibleText(text: string, count: number): string {
  if (count <= 0) {
    return "";
  }
  const pattern = /\S+/g;
  let seen = 0;
  let end = 0;
  let match: RegExpExecArray | null = pattern.exec(text);
  while (match) {
    seen += 1;
    end = match.index + match[0].length;
    if (seen >= count) {
      break;
    }
    match = pattern.exec(text);
  }
  return text.slice(0, end);
}

function spoken(content: string, extra?: Pick<ChatLine, "job" | "chips">): ChatLine {
  return { role: "assistant", content, reveal: wordCount(content) === 0 ? undefined : 1, ...extra };
}

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
  const composer = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<ChatLine[]>([
    {
      role: "assistant",
      content:
        "Ask me to open a page, draft a job, rank applicants, or start a practice call. Approving a role and checking the inbox wait for your confirmation.",
    },
  ]);

  const speaking = lines.some((line) => line.reveal !== undefined);

  useEffect(() => {
    const node = scroller.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [lines, busy, open]);

  useEffect(() => {
    if (open) {
      composer.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    const index = lines.findIndex((line) => line.reveal !== undefined && line.reveal < wordCount(line.content));
    if (index < 0) {
      if (!lines.some((line) => line.reveal !== undefined)) {
        return;
      }
      setLines((current) => current.map((line) => (line.reveal === undefined ? line : { ...line, reveal: undefined })));
      return;
    }
    const timer = window.setTimeout(() => {
      setLines((current) =>
        current.map((line, item) => {
          if (item !== index || line.reveal === undefined) {
            return line;
          }
          const next = line.reveal + 1;
          return next >= wordCount(line.content) ? { ...line, reveal: undefined } : { ...line, reveal: next };
        }),
      );
    }, 48);
    return () => window.clearTimeout(timer);
  }, [lines]);

  if (
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname.startsWith("/invite/") ||
    pathname.startsWith("/interview/")
  ) {
    return null;
  }

  async function follow(result: CopilotTurn) {
    if (result.practice) {
      rememberInterview(result.practice.session_id, result.practice.token, result.practice.role);
      rememberPracticeLink(result.practice.session_id, result.practice.guest_url);
    }
    const href = result.navigation ? safePath(result.navigation.href) : "";
    if (href) {
      router.push(href);
    }
    if (result.report_candidate_id) {
      try {
        await downloadAssessmentReport(result.report_candidate_id);
      } catch (error) {
        const message = error instanceof ApiError ? error.message : "The report could not be downloaded.";
        setLines((current) => [...current, spoken(message)]);
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
        spoken(result.message, { job: result.job, chips: result.chips }),
      ]);
      await follow(result);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "The copilot could not respond.";
      setLines((current) => [...current, spoken(message)]);
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = draft.trim();
    if (!content || busy || speaking) return;
    await send(content);
  }

  async function onChip(chip: CopilotChip) {
    if (busy || speaking) return;
    if (chip.kind === "navigate") {
      const href = safePath(chip.href);
      if (href) router.push(href);
      return;
    }
    if (chip.kind === "confirm") {
      await confirm(chip);
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

  async function confirm(chip: CopilotChip) {
    setBusy(true);
    try {
      if (chip.confirm === "inbox") {
        await apiRequest("/api/v1/screening/poll", { method: "POST" });
        setLines((current) => [
          ...current,
          spoken("Checking the mailbox. Scoring progress shows on the role's Applicants tab."),
        ]);
        return;
      }
      if (chip.confirm === "approve" && chip.job_id && chip.version_number) {
        const locked = await apiRequest<JobRecord>(
          `/api/v1/jobs/${chip.job_id}/versions/${chip.version_number}/approve`,
          { method: "POST" },
        );
        const posted = locked.versions[locked.versions.length - 1];
        setLines((current) => [
          ...current,
          spoken(
            `Checklist locked for ${locked.title}. Posting status: ${posted?.posting_status ?? "unknown"}.${
              posted?.posting_detail?.startsWith("http") ? ` ${posted.posting_detail}` : ""
            }`,
            { job: locked },
          ),
        ]);
        router.push(`/jobs?job=${locked.id}&tab=brief#brief`);
      }
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "That confirmation could not be completed.";
      setLines((current) => [...current, spoken(message)]);
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
        spoken(
          `Checklist locked for ${locked.title}. Posting status: ${posted?.posting_status ?? "unknown"}.${
            posted?.posting_detail?.startsWith("http") ? ` ${posted.posting_detail}` : ""
          }`,
          { job: locked },
        ),
      ]);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Approval failed.";
      setLines((current) => [...current, spoken(message)]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end">
      {open ? (
        <section className="relative mb-3 flex h-[32rem] w-[24rem] max-w-[calc(100vw-2.5rem)] flex-col overflow-hidden rounded-card border border-white/15 bg-[linear-gradient(180deg,rgb(48_24_32/0.48),rgb(18_10_14/0.58))] text-ivory shadow-[inset_0_1px_0_rgb(255_228_220/0.4),0_18px_40px_rgb(20_10_16/0.18)] backdrop-blur-xl">
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
            {lines.map((line, index) => {
              const settled = line.reveal === undefined;
              const text = settled ? line.content : visibleText(line.content, line.reveal ?? 0);
              return (
                <div key={`${line.role}-${index}`} className={line.role === "user" ? "text-right" : "text-left"}>
                  {text ? (
                    <p className="inline-block max-w-[90%] whitespace-pre-wrap rounded-lg bg-night/60 px-3 py-2 text-left text-ivory">
                      {text}
                      {settled ? null : <span className="ml-0.5 inline-block h-3 w-px translate-y-px bg-ivory/80" />}
                    </p>
                  ) : null}
                  {settled && line.job ? <JobCard job={line.job} busy={busy || speaking} onApprove={approve} /> : null}
                  {settled && line.chips && line.chips.length > 0 ? (
                    <div className="mt-2 flex max-w-[90%] flex-wrap gap-2">
                      {line.chips.map((chip) => (
                        <button
                          key={`${chip.kind}-${chip.label}`}
                          type="button"
                          disabled={busy || speaking}
                          onClick={() => onChip(chip)}
                          className="rounded-control border border-ivory/15 px-2 py-1 text-xs text-ivory disabled:opacity-60"
                        >
                          {chip.label}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}
            {busy ? <Thinking /> : null}
          </div>
          <form onSubmit={onSubmit} className="flex gap-2 border-t border-ivory/10 p-3">
            <input
              ref={composer}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Rank candidates for a role..."
              className="min-w-0 flex-1 rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-sm text-ivory placeholder:text-mist/70"
            />
            <button type="submit" disabled={busy || speaking} className="rounded-control bg-action px-3 py-2 text-sm font-semibold text-ivory disabled:opacity-60">
              Send
            </button>
          </form>
        </section>
      ) : null}
      <button
        type="button"
        aria-label={open ? "Close copilot" : "Open copilot"}
        onClick={() => setOpen((current) => !current)}
        className="rounded-full bg-[linear-gradient(180deg,rgb(255_232_226/0.16),rgb(42_22_28/0.32))] px-5 py-2.5 text-sm font-medium tracking-[0.03em] text-ivory shadow-[0_16px_34px_rgb(16_8_12/0.28),inset_0_1px_0_rgb(255_244_240/0.42),inset_0_0_0_1px_rgb(255_228_220/0.12)] backdrop-blur-2xl"
      >
        Copilot
      </button>
    </div>
  );
}

function Thinking() {
  return (
    <div className="inline-flex items-end gap-1.5 rounded-lg bg-night/60 px-3 py-3" aria-label="Thinking">
      <style>{`@keyframes sift-copilot-hop { 0%, 70%, 100% { transform: translateY(0); opacity: 0.35; } 35% { transform: translateY(-6px); opacity: 1; } }`}</style>
      {[0, 1, 2].map((dot) => (
        <span
          key={dot}
          className="block h-1.5 w-1.5 rounded-full bg-[#f6ebe8]"
          style={{ animation: `sift-copilot-hop 1.05s ${dot * 0.16}s infinite` }}
        />
      ))}
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
