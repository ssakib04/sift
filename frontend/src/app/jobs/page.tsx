"use client";

import { FormEvent, Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { AppShell } from "@/components/ui/app-shell";
import { buttonClass } from "@/components/ui/button";
import { fieldClass } from "@/components/ui/field";
import { PageHeader } from "@/components/ui/page-header";
import { ApiError, CandidateRecord, ChecklistQuery, CvUploadResult, JobRecord, apiRequest } from "@/lib/api";

const CATEGORIES = [
  "Information Technology",
  "Engineering",
  "Operations",
  "Human Resources",
  "Research",
  "None",
];

type DraftQuery = ChecklistQuery;

function JobsPageContent() {
  const [job, setJob] = useState<JobRecord | null>(null);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [description, setDescription] = useState("");
  const [queries, setQueries] = useState<DraftQuery[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [candidates, setCandidates] = useState<CandidateRecord[]>([]);
  const requestedJobId = useSearchParams().get("job");

  useEffect(() => {
    let cancelled = false;
    apiRequest<JobRecord[]>("/api/v1/jobs")
      .then((records) => {
        if (!cancelled) setJobs(records);
      })
      .catch(() => {
        if (!cancelled) setJobs([]);
      });
    return () => {
      cancelled = true;
    };
  }, [job?.id]);

  useEffect(() => {
    if (!requestedJobId) return;
    let cancelled = false;
    apiRequest<JobRecord>(`/api/v1/jobs/${requestedJobId}`)
      .then((record) => {
        if (cancelled) return;
        const latest = record.versions[record.versions.length - 1];
        setJob(record);
        setDescription(latest?.description ?? "");
        setQueries(latest?.queries ?? []);
        setMessage("Opened this job.");
      })
      .catch((error: unknown) => {
        if (!cancelled) setMessage(error instanceof ApiError ? error.message : "Could not open that job.");
      });
    return () => {
      cancelled = true;
    };
  }, [requestedJobId]);

  function applyJob(record: JobRecord) {
    const latest = record.versions[record.versions.length - 1];
    setJob(record);
    setDescription(latest?.description ?? "");
    setQueries(latest?.queries ?? []);
    window.history.replaceState(null, "", `/jobs?job=${record.id}`);
  }

  async function onCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      title: String(form.get("title") || ""),
      seniority: String(form.get("seniority") || "Mid-Level"),
      required_skills: String(form.get("required_skills") || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      preferred_skills: String(form.get("preferred_skills") || "")
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      qualifications: String(form.get("qualifications") || ""),
      minimum_years: Number(form.get("minimum_years") || 0),
      technical_weight: Number(form.get("technical_weight") || 0.5),
      experience_weight: Number(form.get("experience_weight") || 0.3),
      qualification_weight: Number(form.get("qualification_weight") || 0.2),
      contract: String(form.get("contract") || "Full Time"),
      category: String(form.get("category") || "Information Technology"),
    };
    setBusy(true);
    setMessage("");
    try {
      const created = await apiRequest<JobRecord>("/api/v1/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      applyJob(created);
      setMessage("Draft generated. Review the description and checklist, then approve to freeze it.");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Job generation failed.");
    } finally {
      setBusy(false);
    }
  }

  async function saveDraft() {
    if (!job) return;
    const latest = job.versions[job.versions.length - 1];
    setBusy(true);
    setMessage("");
    try {
      const updated = await apiRequest<JobRecord>(`/api/v1/jobs/${job.id}/versions/${latest.version_number}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ description, queries }),
      });
      applyJob(updated);
      setMessage("Draft saved.");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Could not save the draft.");
    } finally {
      setBusy(false);
    }
  }

  async function approve() {
    if (!job) return;
    const latest = job.versions[job.versions.length - 1];
    setBusy(true);
    setMessage("");
    try {
      if (latest.status === "draft") {
        await apiRequest<JobRecord>(`/api/v1/jobs/${job.id}/versions/${latest.version_number}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ description, queries }),
        });
      }
      const locked = await apiRequest<JobRecord>(
        `/api/v1/jobs/${job.id}/versions/${latest.version_number}/approve`,
        { method: "POST" },
      );
      applyJob(locked);
      const posted = locked.versions[locked.versions.length - 1];
      setMessage(`Checklist locked. Posting status: ${posted.posting_status ?? "unknown"}.`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Approval failed.");
    } finally {
      setBusy(false);
    }
  }

  async function newVersion() {
    if (!job) return;
    setBusy(true);
    setMessage("");
    try {
      const opened = await apiRequest<JobRecord>(`/api/v1/jobs/${job.id}/versions`, { method: "POST" });
      applyJob(opened);
      setMessage("New draft version opened. The previous checklist stays frozen.");
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Could not open a new version.");
    } finally {
      setBusy(false);
    }
  }

  async function loadCandidates(jobId: string) {
    const rows = await apiRequest<CandidateRecord[]>(`/api/v1/jobs/${jobId}/candidates`);
    setCandidates(rows);
  }

  async function uploadCvs(files: File[]) {
    if (!job || files.length === 0) return;
    if (files.length > 20) {
      setMessage("Upload at most 20 CVs at a time.");
      return;
    }
    const body = new FormData();
    for (const file of files) {
      body.append("files", file);
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await apiRequest<CvUploadResult>(`/api/v1/jobs/${job.id}/cvs`, { method: "POST", body });
      await loadCandidates(job.id);
      const parts = [`${result.scored} scored`];
      if (result.duplicate > 0) parts.push(`${result.duplicate} already stored`);
      if (result.parse_failed > 0) parts.push(`${result.parse_failed} could not be read`);
      if (result.invalid > 0) parts.push(`${result.invalid} were not PDF or DOCX`);
      if (result.failed > 0) parts.push(`${result.failed} failed`);
      setMessage(`Upload finished. ${parts.join(", ")}. Invites go to anyone who newly enters the top 3.`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Could not upload those CVs.");
    } finally {
      setBusy(false);
    }
  }

  async function checkInbox() {
    setBusy(true);
    setMessage("");
    try {
      const result = await apiRequest<{ processed: number }>("/api/v1/screening/poll", { method: "POST" });
      if (job) {
        await loadCandidates(job.id);
      }
      setMessage(`Inbox checked. ${result.processed} new CV${result.processed === 1 ? "" : "s"} scored.`);
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : "Could not read the inbox.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const hasLockedVersion = job?.versions.some((version) => version.status === "locked") ?? false;
    if (!job || !hasLockedVersion) {
      setCandidates([]);
      return;
    }
    let cancelled = false;
    apiRequest<CandidateRecord[]>(`/api/v1/jobs/${job.id}/candidates`)
      .then((rows) => {
        if (!cancelled) setCandidates(rows);
      })
      .catch(() => {
        if (!cancelled) setCandidates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [job]);

  const latest = job?.versions[job.versions.length - 1];
  const locked = latest?.status === "locked";

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl space-y-8">
        <PageHeader eyebrow="Jobs" title="Create a locked job profile" />
        <section className="space-y-3 relative overflow-hidden rounded-card border border-white/10 bg-[linear-gradient(180deg,rgb(72_32_26/0.5),rgb(28_12_12/0.62))] p-5 shadow-[inset_0_1px_0_rgb(255_220_196/0.28),0_12px_28px_rgb(6_2_2/0.2)] backdrop-blur-xl">
          <h2 className="font-display text-2xl font-medium text-ivory">Gmail inbox</h2>
          <p className="text-sm text-mist">
            Pull unread CV emails from the shared apply mailbox, match them to locked jobs, and score them.
          </p>
          <button
            type="button"
            onClick={checkInbox}
            disabled={busy}
            className={buttonClass()}
          >
            {busy ? "Checking inbox..." : "Check inbox"}
          </button>
        </section>
        <section className="space-y-3 relative overflow-hidden rounded-card border border-white/10 bg-[linear-gradient(180deg,rgb(72_32_26/0.5),rgb(28_12_12/0.62))] p-5 shadow-[inset_0_1px_0_rgb(255_220_196/0.28),0_12px_28px_rgb(6_2_2/0.2)] backdrop-blur-xl">
          <h2 className="font-display text-2xl font-medium text-ivory">Open an existing job</h2>
          <p className="text-sm text-mist">
            Open a locked job to review applicants after checking the inbox.
          </p>
          {jobs.length === 0 ? (
            <p className="text-sm text-mist">No jobs yet. Generate a draft below, then approve it.</p>
          ) : (
            <ul className="space-y-2">
              {jobs.map((record) => {
                const version = record.versions[record.versions.length - 1];
                const isOpen = job?.id === record.id;
                return (
                  <li key={record.id}>
                    <button
                      type="button"
                      onClick={() => {
                        applyJob(record);
                        setMessage(`Opened ${record.title}.`);
                      }}
                      className={`w-full rounded-md border px-4 py-3 text-left text-sm ${
                        isOpen ? "border-ivory bg-ivory/10" : "border-ivory/10 hover:border-ivory/30"
                      }`}
                    >
                      <span className="font-medium">{record.title}</span>
                      <span className="mt-1 block text-mist">
                        v{version?.version_number ?? "?"} · {version?.status ?? "unknown"}
                        {version?.status === "locked" ? " · applicants available" : ""}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        <form onSubmit={onCreate} className="grid gap-4 relative overflow-hidden rounded-card border border-white/10 bg-[linear-gradient(180deg,rgb(72_32_26/0.5),rgb(28_12_12/0.62))] p-5 shadow-[inset_0_1px_0_rgb(255_220_196/0.28),0_12px_28px_rgb(6_2_2/0.2)] backdrop-blur-xl">
          <label className="grid gap-1 text-sm">
            Title
            <input name="title" required className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory" />
          </label>
          <label className="grid gap-1 text-sm">
            Seniority
            <select name="seniority" defaultValue="Mid-Level" className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory">
              <option>Junior</option>
              <option>Mid-Level</option>
              <option>Senior</option>
              <option>Not specified</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Required skills
            <input name="required_skills" required placeholder="Python, FastAPI" className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory" />
          </label>
          <label className="grid gap-1 text-sm">
            Preferred skills
            <input name="preferred_skills" placeholder="LangGraph, pgvector" className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory" />
          </label>
          <label className="grid gap-1 text-sm">
            Qualifications
            <input name="qualifications" required className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory" />
          </label>
          <label className="grid gap-1 text-sm">
            Minimum years
            <input name="minimum_years" type="number" min={0} defaultValue={3} className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory" />
          </label>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="grid gap-1 text-sm">
              Technical weight
              <input name="technical_weight" type="number" step="0.01" defaultValue={0.5} className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory" />
            </label>
            <label className="grid gap-1 text-sm">
              Experience weight
              <input name="experience_weight" type="number" step="0.01" defaultValue={0.3} className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory" />
            </label>
            <label className="grid gap-1 text-sm">
              Qualification weight
              <input name="qualification_weight" type="number" step="0.01" defaultValue={0.2} className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory" />
            </label>
          </div>
          <label className="grid gap-1 text-sm">
            Contract
            <select name="contract" defaultValue="Full Time" className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory">
              <option>Full Time</option>
              <option>Part Time</option>
              <option>Freelance</option>
              <option>Internship</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Category
            <select name="category" defaultValue="Information Technology" className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory">
              {CATEGORIES.map((category) => (
                <option key={category}>{category}</option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={busy} className={`w-fit ${buttonClass()}`}>
            {busy ? "Working..." : "Generate draft"}
          </button>
        </form>
        {latest ? (
          <section className="space-y-4 relative overflow-hidden rounded-card border border-white/10 bg-[linear-gradient(180deg,rgb(72_32_26/0.5),rgb(28_12_12/0.62))] p-5 shadow-[inset_0_1px_0_rgb(255_220_196/0.28),0_12px_28px_rgb(6_2_2/0.2)] backdrop-blur-xl">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-display text-2xl font-medium text-ivory">
                {job?.title} · v{latest.version_number} · {latest.status}
              </h2>
            </div>
            <label className="grid gap-1 text-sm">
              Job description
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                readOnly={locked}
                rows={8}
                className="rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory"
              />
            </label>
            <ol className="space-y-3">
              {queries.map((query, index) => (
                <li key={query.query_id} className="rounded-control border border-ivory/10 p-3 text-sm">
                  <p className="text-mist">
                    {query.query_id} · {query.dimension} · {query.requirement_type} · weight {query.weight.toFixed(2)}
                  </p>
                  <textarea
                    value={query.question}
                    readOnly={locked}
                    rows={2}
                    onChange={(event) => {
                      const next = [...queries];
                      next[index] = { ...query, question: event.target.value };
                      setQueries(next);
                    }}
                    className="mt-2 w-full rounded-control border border-ivory/15 bg-night/50 px-3 py-2 text-ivory"
                  />
                </li>
              ))}
            </ol>
            <div className="flex flex-wrap gap-3">
              {locked ? (
                <button type="button" onClick={newVersion} disabled={busy} className={buttonClass()}>
                  New version
                </button>
              ) : (
                <>
                  <button type="button" onClick={saveDraft} disabled={busy} className={buttonClass("secondary")}>
                    Save draft
                  </button>
                  <button type="button" onClick={approve} disabled={busy} className={buttonClass()}>
                    Approve and post
                  </button>
                </>
              )}
            </div>
            {job && job.versions.some((version) => version.status === "locked") ? (
              <section className="space-y-3 border-t border-ivory/10 pt-4">
                <h3 className="font-display text-2xl font-medium text-ivory">Applicants</h3>
                <p className="text-sm text-mist">
                  Email a PDF or DOCX CV to {job.apply_email}. Subject: {job.mail_subject}. The job id {job.id} also matches.
                  Or upload up to 20 CVs for this job. Each file is scored the same way, and invites still go to the top 3.
                </p>
                <div className="flex flex-wrap gap-3">
                  <label className={`${buttonClass("secondary")} cursor-pointer`}>
                    {busy ? "Working..." : "Upload CVs"}
                    <input
                      type="file"
                      accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      multiple
                      disabled={busy}
                      className="sr-only"
                      onChange={(event) => {
                        const chosen = event.target.files ? Array.from(event.target.files) : [];
                        event.target.value = "";
                        void uploadCvs(chosen);
                      }}
                    />
                  </label>
                  <button type="button" onClick={checkInbox} disabled={busy} className={buttonClass("secondary")}>
                    Check inbox
                  </button>
                </div>
                <ul className="space-y-2">
                  {candidates.map((candidate) => (
                    <li key={candidate.id} className="rounded-control border border-ivory/10 p-3 text-sm">
                      <p>
                        {candidate.rank ? `#${candidate.rank}` : "Unranked"} · {candidate.full_name || "Unnamed"} · {candidate.email}
                      </p>
                      <p className="text-mist">
                        {candidate.parse_status}
                        {candidate.aggregate_score !== null ? ` · score ${candidate.aggregate_score.toFixed(2)}` : ""}
                        {candidate.invited ? " · invited" : ""}
                      </p>
                    </li>
                  ))}
                </ul>
              </section>
            ) : null}
            {latest.apply_url ? (
              <p className="text-sm text-mist">
                Public listing: <a className="underline" href={latest.apply_url}>{latest.apply_url}</a>
                {latest.posting_detail?.startsWith("http") ? (
                  <>
                    {" "}
                    · Channel: <a className="underline" href={latest.posting_detail}>{latest.posting_detail}</a>
                  </>
                ) : latest.external_posting_id ? (
                  ` · PostAJob ${latest.external_posting_id}`
                ) : null}
              </p>
            ) : null}
          </section>
        ) : null}
        {message ? <p className="text-sm text-mist">{message}</p> : null}
      </div>
    </AppShell>
  );
}

export default function JobsPage() {
  return (
    <Suspense fallback={<AppShell><p className="text-sm text-mist">Opening jobs…</p></AppShell>}>
      <JobsPageContent />
    </Suspense>
  );
}
