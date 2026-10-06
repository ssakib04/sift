"use client";

import { FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import { SectionLinks } from "@/components/section-links";
import { ApiError, ChecklistQuery, JobRecord, apiRequest } from "@/lib/api";

const CATEGORIES = [
  "Information Technology",
  "Engineering",
  "Operations",
  "Human Resources",
  "Research",
  "None",
];

type DraftQuery = ChecklistQuery;

export default function JobsPage() {
  const [job, setJob] = useState<JobRecord | null>(null);
  const [description, setDescription] = useState("");
  const [queries, setQueries] = useState<DraftQuery[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const requestedJobId = useSearchParams().get("job");

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

  const latest = job?.versions[job.versions.length - 1];
  const locked = latest?.status === "locked";

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
      <div className="mx-auto max-w-3xl space-y-8">
        <SectionLinks />
        <header className="space-y-2">
          <p className="text-sm uppercase tracking-[0.2em] text-slate-400">Jobs</p>
          <h1 className="text-3xl font-semibold">Create a locked job profile</h1>
        </header>
        <form onSubmit={onCreate} className="grid gap-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
          <label className="grid gap-1 text-sm">
            Title
            <input name="title" required className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2" />
          </label>
          <label className="grid gap-1 text-sm">
            Seniority
            <select name="seniority" defaultValue="Mid-Level" className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2">
              <option>Junior</option>
              <option>Mid-Level</option>
              <option>Senior</option>
              <option>Not specified</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Required skills
            <input name="required_skills" required placeholder="Python, FastAPI" className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2" />
          </label>
          <label className="grid gap-1 text-sm">
            Preferred skills
            <input name="preferred_skills" placeholder="LangGraph, pgvector" className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2" />
          </label>
          <label className="grid gap-1 text-sm">
            Qualifications
            <input name="qualifications" required className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2" />
          </label>
          <label className="grid gap-1 text-sm">
            Minimum years
            <input name="minimum_years" type="number" min={0} defaultValue={3} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2" />
          </label>
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="grid gap-1 text-sm">
              Technical weight
              <input name="technical_weight" type="number" step="0.01" defaultValue={0.5} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2" />
            </label>
            <label className="grid gap-1 text-sm">
              Experience weight
              <input name="experience_weight" type="number" step="0.01" defaultValue={0.3} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2" />
            </label>
            <label className="grid gap-1 text-sm">
              Qualification weight
              <input name="qualification_weight" type="number" step="0.01" defaultValue={0.2} className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2" />
            </label>
          </div>
          <label className="grid gap-1 text-sm">
            Contract
            <select name="contract" defaultValue="Full Time" className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2">
              <option>Full Time</option>
              <option>Part Time</option>
              <option>Freelance</option>
              <option>Internship</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm">
            Category
            <select name="category" defaultValue="Information Technology" className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2">
              {CATEGORIES.map((category) => (
                <option key={category}>{category}</option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={busy} className="w-fit rounded-md bg-white px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-60">
            {busy ? "Working..." : "Generate draft"}
          </button>
        </form>
        {latest ? (
          <section className="space-y-4 rounded-xl border border-slate-800 bg-slate-900 p-5">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-xl font-semibold">
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
                className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2"
              />
            </label>
            <ol className="space-y-3">
              {queries.map((query, index) => (
                <li key={query.query_id} className="rounded-md border border-slate-800 p-3 text-sm">
                  <p className="text-slate-400">
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
                    className="mt-2 w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2"
                  />
                </li>
              ))}
            </ol>
            <div className="flex flex-wrap gap-3">
              {locked ? (
                <button type="button" onClick={newVersion} disabled={busy} className="rounded-md bg-white px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-60">
                  New version
                </button>
              ) : (
                <>
                  <button type="button" onClick={saveDraft} disabled={busy} className="rounded-md border border-slate-600 px-4 py-2 text-sm disabled:opacity-60">
                    Save draft
                  </button>
                  <button type="button" onClick={approve} disabled={busy} className="rounded-md bg-white px-4 py-2 text-sm font-medium text-slate-950 disabled:opacity-60">
                    Approve and post
                  </button>
                </>
              )}
            </div>
            {latest.apply_url ? (
              <p className="text-sm text-slate-300">
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
        {message ? <p className="text-sm text-slate-300">{message}</p> : null}
      </div>
    </main>
  );
}
